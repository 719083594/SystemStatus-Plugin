import test from "node:test"
import assert from "node:assert/strict"
import { buildHtml, levelColor } from "../lib/html.mjs"

const GiB = 1024 ** 3
const host = {
  host: {
    hostname: "demo-host", os: "Ubuntu 26.04.1 LTS", kernel: "7.0.0-42-generic", uptime: 9061, cores: 2,
    cpuPercent: 95.5, load: [0.19, 0.13, 0.1],
    memory: { total: 8 * GiB, used: 2 * GiB, available: 6 * GiB, swapTotal: 2 * GiB, swapUsed: 0 },
    disks: [{ mount: "/", type: "ext4", total: 100 * GiB, used: 80 * GiB, available: 20 * GiB }],
  },
  docker: {
    available: true,
    df: [{ type: "Images", size: "4.4GB", reclaimable: "0B", total: 3 }],
    containers: [
      { name: "demo-bot", running: true, health: "healthy", restarts: 0, cpu: "0.5%", memory: "208MiB / 1.5GiB" },
      { name: "demo-cache", running: false, status: "exited", restarts: 2 },
    ],
  },
}
const bot = {
  framework: { name: "TRSS-Yunzai", version: "3.1.3" }, node: "v24.22.2", uptime: 3700, rss: 120 * 1024 ** 2,
  accounts: [{ id: "10001", nickname: "<b>坏</b>", adapter: "OneBotv11" }],
  plugins: [{ title: "系统状态", version: "1.0.0" }],
}

test("colours follow the old thresholds", () => {
  assert.equal(levelColor(10), "#1985e4")
  assert.equal(levelColor(80), "#e5a02b")
  assert.equal(levelColor(95), "#e15353")
})

test("page has every card and is self-contained", () => {
  const html = buildHtml({ host, bot, now: Date.UTC(2026, 9, 30, 16, 5) })
  for (const part of ["服务器运行总览", "2026-10-31 00:05", "核心资源", "95.5%", "物理内存", "25.0%", "运行信息", "硬盘与存储",
    "80.0% 已用", "服务运行与占用", "demo-bot", "健康", "已停止", "镜像 3 个", "机器人", "已加载插件 · 1 个"]) {
    assert.ok(html.includes(part), part)
  }
  assert.doesNotMatch(html, /<script|<link|https?:\/\//i)
  assert.doesNotMatch(html, /\{\{/, "must not contain art-template syntax")
})

test("footer shows the sample time", () => {
  const html = buildHtml({ host: { ...host, collectedAt: Date.UTC(2026, 9, 30, 16, 23, 45), refreshSeconds: 15 }, bot })
  assert.ok(html.includes("服务器数据采集于 00:23:45（采集完成后间隔 15 秒）"))
})

test("page warns about cached sampling failure and incomplete Docker data", () => {
  const partial = structuredClone(host)
  partial.collectedAt = Date.now()
  partial.sampling = {healthy:false,ageSeconds:20,maxAgeSeconds:60}
  partial.docker.errors = {stats:"CalledProcessError"}
  partial.docker.containers = [{name:"unknown-container",running:null,restarts:null}]
  const html = buildHtml({host:partial,bot})
  for (const expected of ["最近采集失败，显示上次成功数据","Docker 部分数据不可用：容器用量","状态未知","重启 ?次"])
    assert.ok(html.includes(expected),expected)
  assert.ok(html.includes("硬盘与存储"))
  assert.ok(html.includes("机器人"))
})

test("user-controlled text is escaped", () => {
  const html = buildHtml({ host, bot })
  assert.ok(html.includes("&lt;b&gt;坏&lt;/b&gt;"))
  assert.ok(!html.includes("<b>坏</b>"))
})

test("collector failure still renders the bot cards", () => {
  const html = buildHtml({ hostError: "连接不上采集器", bot })
  assert.ok(html.includes("服务器数据获取失败：连接不上采集器"))
  assert.ok(html.includes("已加载插件"))
})
