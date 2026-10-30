import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { COMMAND_REG } from "../lib/command.mjs"
import { loadConfig } from "../lib/config.mjs"
import { fetchHostStatus } from "../lib/client.mjs"
import { formatReport, size, duration, timestamp, collectedNote, reclaimText } from "../lib/format.mjs"

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const GiB = 1024 ** 3

const host = {
  host: {
    hostname: "demo-host", os: "Ubuntu 26.04.1 LTS", kernel: "7.0.0-42-generic", uptime: 90061, cores: 2,
    cpuPercent: 3.2, load: [0.19, 0.13, 0.1],
    memory: { total: 7.4 * GiB, used: 1.2 * GiB, available: 6.2 * GiB, swapTotal: 2 * GiB, swapUsed: 0 },
    disks: [{ mount: "/", type: "ext4", total: 118 * GiB, used: 13 * GiB, available: 101 * GiB }],
  },
  docker: {
    available: true,
    df: [{ type: "Images", size: "5.886GB", reclaimable: "0B", total: 3, active: 3 }],
    containers: [
      { name: "demo-bot", running: true, health: "healthy", restarts: 0, cpu: "0.47%", memory: "208MiB / 1.5GiB" },
      { name: "demo-cache", running: false, status: "exited", health: null, restarts: 2 },
    ],
  },
}
const bot = {
  framework: { name: "TRSS-Yunzai", version: "3.1.3" }, node: "v24.22.2", uptime: 3700, rss: 120 * 1024 ** 2,
  accounts: [{ id: "10001", nickname: "测试", adapter: "OneBotv11", received: 12, sent: 5 }],
  plugins: [{ title: "TRSS 系统功能", version: "" }, { title: "系统状态", version: "1.0.0" }],
}

test("manifest commands match the real rule", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.manifest.json"), "utf8"))
  assert.equal(manifest.schemaVersion, 1)
  assert.ok(manifest.commands.length > 0)
  for (const c of manifest.commands) assert.match(c.command, COMMAND_REG, c.command)
})

test("manifest config files exist inside the plugin", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.manifest.json"), "utf8"))
  for (const c of manifest.configs) {
    assert.ok(!path.isAbsolute(c.file) && !c.file.includes(".."))
    assert.ok(fs.existsSync(path.join(ROOT, c.defaults)), c.defaults)
  }
})

test("command accepts only #系统状态", () => {
  for (const ok of ["#系统状态", "# 系统状态", "#系统状态 "]) assert.match(ok, COMMAND_REG)
  for (const no of ["#系统", "#系统状态图", "系统状态", "#状态"]) assert.doesNotMatch(no, COMMAND_REG)
})

test("helpers format sizes, durations and Shanghai time", () => {
  assert.equal(size(512), "512B")
  assert.equal(size(1.5 * 1024 ** 2), "1.5M")
  assert.equal(size(118 * GiB), "118G")
  assert.equal(size(undefined), "未知")
  assert.equal(duration(90061), "1天1小时")
  assert.equal(duration(3700), "1小时1分")
  assert.equal(timestamp(Date.UTC(2026, 9, 30, 16, 5)), "2026-10-31 00:05")
})

test("full report has every section", () => {
  const text = formatReport({ host, bot, now: Date.UTC(2026, 9, 30, 16, 5) })
  for (const part of ["【系统状态】2026-10-31 00:05", "━ 服务器", "CPU 3.2%（2 核）", "━ 磁盘", "/（ext4） 13G / 118G（11%）",
    "━ Docker", "镜像 3 个 5.886GB", "✅ demo-bot healthy", "⚠️ demo-cache exited · 重启 2", "━ 机器人",
    "10001（测试） OneBotv11 · 收 12 发 5", "━ 插件（2 个）", "系统状态 1.0.0"]) assert.ok(text.includes(part), part)
})

test("image reclaim text never trusts Docker's own figure", () => {
  assert.equal(reclaimText({ type: "Images", reclaimable: "5.886GB (100%)", unusedCount: 0, reclaimableBytes: 0 }), "可回收 0B（都在使用）")
  assert.equal(reclaimText({ type: "Images", unusedCount: 2, reclaimableBytes: 150 * 1024 ** 2 }), "可回收 150M（2 个未使用）")
  assert.equal(reclaimText({ type: "Images", reclaimable: "5.886GB (100%)" }), "可回收 未知")
  assert.equal(reclaimText({ type: "Build Cache", reclaimable: "12.29kB" }), "可回收 12.29kB")
})

test("report says when the background sample was taken", () => {
  const sampled = { ...host, collectedAt: Date.UTC(2026, 9, 30, 16, 23, 45), refreshSeconds: 15 }
  assert.equal(collectedNote(sampled), "服务器数据采集于 00:23:45（每 15 秒后台采集）")
  assert.equal(collectedNote(undefined), "")
  assert.ok(formatReport({ host: sampled, bot }).endsWith("服务器数据采集于 00:23:45（每 15 秒后台采集）"))
})

test("collector failure still shows the bot part", () => {
  const text = formatReport({ hostError: "连接不上采集器", bot })
  assert.ok(text.includes("⚠️ 服务器数据获取失败：连接不上采集器"))
  assert.ok(text.includes("━ 机器人"))
})

test("config merges defaults, override and env token", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ss-"))
  fs.mkdirSync(path.join(dir, "config"))
  fs.copyFileSync(path.join(ROOT, "config/defaults.json"), path.join(dir, "config/defaults.json"))
  fs.writeFileSync(path.join(dir, "config/config.json"), JSON.stringify({ timeoutMs: 3000 }))
  const config = loadConfig(dir, { SYSTEM_STATUS_TOKEN: "t".repeat(64) })
  assert.equal(config.timeoutMs, 3000)
  assert.equal(config.collectorUrl, "http://host.docker.internal:15090")
  assert.equal(config.token, "t".repeat(64))
  fs.rmSync(dir, { recursive: true })
})

test("client sends the token and explains failures", async () => {
  let seen
  const ok = async (url, init) => {
    seen = { url: String(url), auth: init.headers.Authorization }
    return { ok: true, status: 200, json: async () => host }
  }
  assert.deepEqual(await fetchHostStatus({ collectorUrl: "http://x:1", token: "abc" }, ok), host)
  assert.deepEqual(seen, { url: "http://x:1/v1/status", auth: "Bearer abc" })
  const denied = async () => ({ ok: false, status: 401 })
  await assert.rejects(fetchHostStatus({ collectorUrl: "http://x:1", token: "abc" }, denied), /token 不一致/)
  const down = async () => { throw new TypeError("fetch failed") }
  await assert.rejects(fetchHostStatus({ collectorUrl: "http://x:1", token: "abc" }, down), /连接不上采集器/)
  await assert.rejects(fetchHostStatus({ collectorUrl: "http://x:1", token: "" }, ok), /未配置采集器 token/)
})
