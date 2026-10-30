// Builds the status dashboard as one self-contained HTML page (inline CSS, no network, no scripts).
// Pure function: the framework adapter only screenshots it. Style follows the old ServerStatus image.
import { size, duration, timestamp, collectedNote, reclaimText } from "./format.mjs"

const escape = value =>
  String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c])

export const levelColor = percent => (percent < 75 ? "#1985e4" : percent < 90 ? "#e5a02b" : "#e15353")

const ratio = (used, total) => (total > 0 ? (used / total) * 100 : 0)

function gauge(label, percent, subtitle) {
  const p = Math.max(0, Math.min(100, percent))
  return `<div class="gauge"><div class="label">${escape(label)}</div>
<div class="value" style="color:${levelColor(percent)}">${percent.toFixed(1)}%</div>
<div class="bar"><i style="width:${p > 0 ? Math.max(p, 4) : 0}%;background:${levelColor(percent)}"></i></div>
<div class="sub">${escape(subtitle)}</div></div>`
}

const card = (title, body, note = "") =>
  `<section><h2>${escape(title)}</h2>${body}${note ? `<p class="note">${escape(note)}</p>` : ""}</section>`

const DOCKER_TYPES = { Images: "镜像", Containers: "容器", "Local Volumes": "数据卷", "Build Cache": "构建缓存" }
const HEALTH = { healthy: ["健康", "ok"], unhealthy: ["不健康", "bad"], starting: ["启动中", "warn"] }

function containerState(c) {
  if (!c.running) return [c.status === "exited" ? "已停止" : c.status || "已停止", "bad"]
  return HEALTH[c.health] || ["运行中", "ok"]
}

function hostCards(snapshot, bot) {
  const h = snapshot.host
  const m = h.memory
  const cards = [
    card(
      "核心资源 · CPU 为全部核心平均占用",
      `<div class="gauges">${gauge("CPU", h.cpuPercent, `${h.cores} 核 · 0.5秒采样`)}${gauge(
        "物理内存",
        ratio(m.used, m.total),
        `${size(m.used)} / ${size(m.total)}`,
      )}${gauge("交换内存", ratio(m.swapUsed, m.swapTotal), `${size(m.swapUsed)} / ${size(m.swapTotal)}`)}</div>`,
    ),
    card(
      "运行信息",
      `<div class="rows">
<p>服务器已运行：${escape(duration(h.uptime))}　　机器人：${escape(duration(bot?.uptime))}</p>
<p>系统负载：${escape(h.load.map(n => n.toFixed(2)).join(" / "))}　　${escape(h.os)}</p>
<p class="small">主机 ${escape(h.hostname)} · 内核 ${escape(h.kernel)}</p></div>`,
      "内存已用 = 总量 - MemAvailable；包含系统和全部服务，不含可回收缓存。",
    ),
    card(
      "硬盘与存储",
      h.disks
        .map(d => {
          const p = ratio(d.used, d.total)
          return `<div class="disk"><p>磁盘 ${escape(d.mount)}（${escape(d.type)}）<b style="color:${levelColor(p)}">${p.toFixed(
            1,
          )}% 已用</b></p><div class="bar"><i style="width:${Math.max(p, 2)}%;background:${levelColor(p)}"></i></div>
<p class="small">已用 ${escape(size(d.used))} / 总量 ${escape(size(d.total))}　可用 ${escape(size(d.available))}</p></div>`
        })
        .join("") || `<p>没有找到磁盘</p>`,
    ),
  ]
  const docker = snapshot.docker
  if (!docker?.available) {
    cards.push(card("服务运行与占用", `<p class="bad">无法读取 Docker 状态</p>`))
    return cards
  }
  const usage = docker.df
    .map(
      d =>
        `<div class="kv"><span>${escape(DOCKER_TYPES[d.type] || d.type)} ${escape(d.total)} 个</span><span>${escape(
          d.size,
        )}<em>${escape(reclaimText(d))}</em></span></div>`,
    )
    .join("")
  const services = docker.containers
    .map(c => {
      const [state, cls] = containerState(c)
      const detail = c.running ? `内存 ${escape(c.memory ?? "?")}　重启 ${escape(c.restarts)}次` : `重启 ${escape(c.restarts)}次`
      return `<div class="svc"><div><p>${escape(c.name)}</p><p class="small">${detail}</p></div><b class="${cls}">${escape(
        state,
      )}</b><span>${c.running ? `CPU ${escape(c.cpu ?? "?")}` : ""}</span></div>`
    })
    .join("")
  cards.push(
    card(
      "服务运行与占用 · 容器 CPU 以单核100%计",
      `${services}<div class="divider"></div>${usage}`,
      "内存数字为 Docker 统计口径；不能和宿主机占用直接相加。",
    ),
  )
  return cards
}

function botCards(bot) {
  const accounts =
    bot.accounts
      .map(
        a => `<div class="svc"><div><p>${escape(a.id)}${a.nickname ? `（${escape(a.nickname)}）` : ""}</p>
<p class="small">${escape(a.adapter || "未知协议")}${a.received === undefined ? "" : `　收 ${escape(a.received)} 发 ${escape(a.sent)}`}</p></div>
<b class="ok">已连接</b><span></span></div>`,
      )
      .join("") || `<p class="bad">没有在线的账号</p>`
  const plugins = bot.plugins
    .map(p => `<span class="chip">${escape(p.title)}${p.version ? ` <em>${escape(p.version)}</em>` : ""}</span>`)
    .join("")
  return [
    card(
      "机器人",
      `${accounts}<p class="small">${escape(bot.framework.name)} ${escape(bot.framework.version)} · Node ${escape(
        bot.node,
      )} · 进程内存 ${escape(size(bot.rss))}</p>`,
    ),
    card(`已加载插件 · ${bot.plugins.length} 个`, `<div class="chips">${plugins || "无"}</div>`),
  ]
}

const STYLE = `*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;background:#eef3f9;font-family:"Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif;color:#35465a}
#container{padding:28px 28px 30px}
header{background:#162d49;border-radius:24px;padding:22px 32px 26px;position:relative;margin-bottom:20px}
header h1{color:#fff;font-size:40px;font-weight:500}
header p{color:#a4c7ec;font-size:24px;margin-top:10px}
header time{position:absolute;right:40px;bottom:28px;color:#a4c7ec;font-size:21px}
section{background:#fff;border-radius:22px;padding:20px 28px 24px;margin-bottom:20px}
h2{color:#162d49;font-size:28px;font-weight:500;margin-bottom:16px}
.gauges{display:flex;justify-content:space-between}
.gauge{width:290px}.gauge .label{font-size:24px}.gauge .value{font-size:43px;margin:4px 0 12px}
.bar{height:14px;border-radius:7px;background:#e9eff6;overflow:hidden}.bar i{display:block;height:100%;border-radius:7px}
.sub,.small{font-size:20px;color:#758399}.gauge .sub{margin-top:16px}
.rows p{font-size:24px;margin-bottom:10px}.rows p.small{font-size:20px;margin:0}
.disk{margin-bottom:16px}.disk p{font-size:26px;margin-bottom:10px}.disk p b{font-weight:400;margin-left:22px}.disk p.small{font-size:21px;margin:10px 0 0}
.svc{display:grid;grid-template-columns:1fr 200px 200px;align-items:start;margin-bottom:14px}
.svc p{font-size:24px}.svc p.small{font-size:20px;margin-top:4px}.svc b{font-size:23px;font-weight:400}.svc span{font-size:22px}
.ok{color:#139a6a}.warn{color:#e5a02b}.bad{color:#e15353}
.divider{height:1px;background:#e9eff6;margin:6px 0 14px}
.kv{display:flex;justify-content:space-between;font-size:22px;margin-bottom:8px}.kv em{font-style:normal;color:#758399;font-size:19px;margin-left:16px}
.chips{display:flex;flex-wrap:wrap;gap:12px}.chip{background:#eef3f9;border-radius:14px;padding:8px 16px;font-size:21px}.chip em{font-style:normal;color:#758399}
.note{font-size:18px;color:#758399;margin-top:10px}
footer{font-size:20px;color:#758399;padding:0 28px}`

export function buildHtml({ host, hostError, bot, now = Date.now(), timeZone }) {
  const cards = host
    ? hostCards(host, bot)
    : [card("服务器", `<p class="bad">服务器数据获取失败：${escape(hostError || "未知原因")}</p>`)]
  if (bot) cards.push(...botCards(bot))
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>${STYLE}</style></head>
<body><div id="container"><header><h1>服务器运行总览</h1><p>Linux 宿主机 · 系统状态</p><time>${escape(
    timestamp(now, timeZone),
  )}</time></header>${cards.join("")}<footer>#系统状态 · 仅主人可用${
    host ? ` · ${escape(collectedNote(host, timeZone))}` : ""
  }</footer></div></body></html>`
}
