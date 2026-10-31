// Turns a host snapshot (from the collector) and a bot snapshot (from the framework adapter) into chat text.
// Pure functions: no framework, no network, no file access.

export function size(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes)) return "未知"
  const units = ["B", "K", "M", "G", "T"]
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  const text = value >= 100 || i === 0 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, "")
  return `${text}${units[i]}`
}

export function duration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "未知"
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d) return `${d}天${h}小时`
  if (h) return `${h}小时${m}分`
  return `${m}分`
}

/** A registered protocol connection is not proof that the account is online. */
export function accountState(account) {
  if (account.connected === false) return { label: "连接已断开", color: "bad" }
  if (account.online === false) return { label: "账号已离线", color: "bad" }
  if (account.good === false) return { label: "状态异常", color: "warn" }
  if (account.online === true) return { label: "在线", color: "ok" }
  return { label: account.connected === true ? "已连接，在线状态未知" : "在线状态未知", color: "warn" }
}

const percent = (used, total) => (total > 0 ? `${Math.round((used / total) * 100)}%` : "0%")

function clockParts(ms, timeZone) {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(ms))
      .map(p => [p.type, p.value]),
  )
}

export function timestamp(ms, timeZone = "Asia/Shanghai") {
  const p = clockParts(ms, timeZone)
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`
}

/** "数据采集于 00:23:45（每 15 秒）" — the collector samples in the background, so data can be slightly older. */
export function collectedNote(snapshot, timeZone = "Asia/Shanghai") {
  if (!snapshot?.collectedAt) return ""
  const p = clockParts(snapshot.collectedAt, timeZone)
  const every = snapshot.refreshSeconds ? `（采集完成后间隔 ${snapshot.refreshSeconds} 秒）` : ""
  const warning = snapshot.sampling?.healthy === false ? " · ⚠️ 最近采集失败，显示上次成功数据" : ""
  return `服务器数据采集于 ${p.hour}:${p.minute}:${p.second}${every}${warning}`
}

export function dockerNote(docker) {
  const sections = { df: "磁盘占用", images: "镜像回收估算", containers: "容器列表", stats: "容器用量", inspect: "容器详情" }
  const failed = Object.keys(docker?.errors || {}).map(key => sections[key] || "其他项目")
  return [
    failed.length ? `Docker 部分数据不可用：${failed.join("、")}` : "",
    docker?.truncated ? "容器列表仅显示前 50 个" : "",
  ].filter(Boolean).join("；")
}

const DOCKER_TYPES = { Images: "镜像", Containers: "容器", "Local Volumes": "数据卷", "Build Cache": "构建缓存" }

/** "可回收 0B" for most rows; images use the collector's own count of images no container uses. */
export function reclaimText(row) {
  if (row.type === "Images") {
    if (typeof row.reclaimableBytes !== "number") return "可回收 未知"
    return row.unusedCount ? `可回收 ${size(row.reclaimableBytes)}（${row.unusedCount} 个未使用）` : "可回收 0B（都在使用）"
  }
  return `可回收 ${row.reclaimable ?? "未知"}`
}

function hostLines(host) {
  const m = host.memory
  const lines = [
    "━ 服务器",
    `${host.hostname} · ${host.os} · 内核 ${host.kernel}`,
    `已运行 ${duration(host.uptime)}`,
    `CPU ${host.cpuPercent}%（${host.cores} 核） 负载 ${host.load.map(n => n.toFixed(2)).join(" / ")}`,
    `内存 ${size(m.used)} / ${size(m.total)}（${percent(m.used, m.total)}） 可用 ${size(m.available)}`,
    `Swap ${size(m.swapUsed)} / ${size(m.swapTotal)}`,
    "━ 磁盘",
    ...host.disks.map(
      d => `${d.mount}（${d.type}） ${size(d.used)} / ${size(d.total)}（${percent(d.used, d.total)}） 可用 ${size(d.available)}`,
    ),
  ]
  return lines
}

function dockerLines(docker) {
  if (!docker?.available) return ["━ Docker", "无法读取 Docker 状态"]
  const lines = ["━ Docker"]
  if (dockerNote(docker)) lines.push(`⚠️ ${dockerNote(docker)}`)
  for (const d of docker.df) {
    const label = DOCKER_TYPES[d.type] || d.type
    lines.push(`${label} ${d.total} 个 ${d.size}（${reclaimText(d)}）`)
  }
  for (const c of docker.containers) {
    const ok = c.running === true && (c.health === null || c.health === undefined || c.health === "healthy")
    const state = typeof c.running !== "boolean" ? "状态未知" : c.running ? c.health || "运行中" : c.status || "已停止"
    const usage = c.running ? ` · CPU ${c.cpu ?? "?"} · 内存 ${c.memory ?? "?"}` : ""
    lines.push(`${ok ? "✅" : "⚠️"} ${c.name} ${state} · 重启 ${c.restarts ?? "?"}${usage}`)
  }
  return lines
}

function botLines(bot) {
  const lines = [
    "━ 机器人",
    `${bot.framework.name} ${bot.framework.version} · Node ${bot.node} · 运行 ${duration(bot.uptime)} · 内存 ${size(bot.rss)}`,
  ]
  if (!bot.accounts.length) lines.push("⚠️ 没有在线的账号")
  for (const a of bot.accounts) {
    const name = a.nickname ? `（${a.nickname}）` : ""
    const traffic = a.received === undefined ? "" : ` · 收 ${a.received} 发 ${a.sent}`
    lines.push(`${a.id}${name} ${a.adapter || "未知协议"}${traffic} · ${accountState(a).label}`)
  }
  lines.push(`━ 插件（${bot.plugins.length} 个）`)
  lines.push(bot.plugins.map(p => `${p.title}${p.version ? " " + p.version : ""}`).join(" · ") || "无")
  return lines
}

export function formatReport({ host, hostError, bot, now = Date.now(), timeZone }) {
  const lines = [`【系统状态】${timestamp(now, timeZone)}`]
  if (host) lines.push(...hostLines(host.host), ...dockerLines(host.docker))
  else lines.push("━ 服务器", `⚠️ 服务器数据获取失败：${hostError || "未知原因"}`)
  if (bot) lines.push(...botLines(bot))
  const note = collectedNote(host, timeZone)
  if (note) lines.push(note)
  return lines.join("\n")
}
