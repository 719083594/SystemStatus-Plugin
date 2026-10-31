import test, { after, beforeEach } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const source = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const tempRoot = fs.realpathSync(os.tmpdir())
const fixture = fs.mkdtempSync(path.join(tempRoot, "systemstatus-adapter-"))
const root = path.join(fixture, "plugins", "SystemStatus-Plugin")
fs.mkdirSync(root, { recursive: true })
fs.writeFileSync(path.join(fixture, "package.json"), '{"type":"module"}')
for (const name of ["index.js", "package.json", "plugin.manifest.json", "lib", "config", "resources"])
  fs.cpSync(path.join(source, name), path.join(root, name), { recursive: true })
for (const [name, value] of [
  ["lib/config/config.js", "export default globalThis.__systemStatusTest.cfg"],
  ["lib/plugins/loader.js", "export default globalThis.__systemStatusTest.loader"],
  ["lib/renderer/loader.js", "export default {render:(...a)=>globalThis.__systemStatusTest.render(...a)}"],
]) {
  const file = path.join(fixture, name)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, value)
}
const original = { fetch: globalThis.fetch, token: process.env.SYSTEM_STATUS_TOKEN }
const ctx = { cfg: { package: { version: "3.1.3" } }, loader: { pluginCountMap: new Map() } }
globalThis.__systemStatusTest = ctx
globalThis.plugin = class { constructor(options) { this.options = options } }
globalThis.segment = { image: data => ({ type: "image", data }) }
globalThis.logger = { error: () => {}, warn: () => {} }
const { SystemStatus } = await import(pathToFileURL(path.join(root, "index.js")).href)
const app = new SystemStatus()
const valid = {
  host: {hostname:"test",os:"Linux",kernel:"test",uptime:1,cores:2,cpuPercent:1,
    load:[0,0,0],memory:{used:1,total:2,available:1,swapUsed:0,swapTotal:0},disks:[]},
  docker:{available:false},
}
beforeEach(() => {
  const override = path.join(root, "config", "config.json")
  if (fs.existsSync(override)) fs.unlinkSync(override)
  process.env.SYSTEM_STATUS_TOKEN = "test-token"
  globalThis.Bot = { uin: ["1"], "1": { nickname:"test",adapter:{name:"OneBotv11"},
    ws:{readyState:1},stat:{online:true,good:true} } }
  globalThis.fetch = async () => ({ok:true,status:200,json:async()=>valid})
  ctx.html = ""
  ctx.render = async (_name, data) => { ctx.html = data.html; return Buffer.from("png") }
})
after(() => {
  globalThis.fetch = original.fetch
  if (original.token === undefined) delete process.env.SYSTEM_STATUS_TOKEN
  else process.env.SYSTEM_STATUS_TOKEN = original.token
  delete globalThis.__systemStatusTest
  const target = fs.realpathSync(fixture)
  assert.ok(target.startsWith(tempRoot + path.sep))
  fs.rmSync(target, {recursive:true})
})
const event = handler => {
  const calls = []
  return {calls,reply:async value => {
    calls.push(value)
    return handler ? handler(value) : {message_id:"ok"}
  }}
}
test("adapter keeps the real command restricted to master", () => {
  assert.equal(app.options.rule[0].permission, "master")
  assert.match("#系统状态", app.options.rule[0].reg)
})
test("successful image is sent once", async () => {
  const e = event()
  assert.equal(await app.status(e), true)
  assert.equal(e.calls.length, 1)
  assert.equal(e.calls[0].type, "image")
})
for (const mode of ["false", "error-object", "throw"]) {
  test("failed image falls back to one text message: " + mode, async () => {
    const e = event(value => {
      if (typeof value === "string") return {message_id:"text"}
      if (mode === "throw") throw new Error("upload failed")
      return mode === "false" ? false : {error:[new Error("upload failed")]}
    })
    await app.status(e)
    assert.equal(e.calls.length, 2)
    assert.equal(typeof e.calls[1], "string")
    assert.match(e.calls[1], /系统状态/)
  })
}
test("render failure sends text", async () => {
  ctx.render = async () => { throw new Error("browser unavailable") }
  const e = event()
  await app.status(e)
  assert.equal(e.calls.length, 1)
  assert.equal(typeof e.calls[0], "string")
})
test("text failure is bounded and does not reject the handler", async () => {
  ctx.render = async () => false
  const e = event(() => { throw new Error("send failed") })
  await assert.doesNotReject(app.status(e))
  assert.equal(e.calls.length, 1)
})
for (const [name, content] of [
  ["invalid JSON", "{"],
  ["invalid time zone", JSON.stringify({timeZone:"Invalid/Timezone"})],
]) {
  test("configuration error still replies: " + name, async () => {
    fs.writeFileSync(path.join(root,"config","config.json"),content)
    const e = event()
    await app.status(e)
    assert.equal(e.calls.length, 1)
    assert.match(ctx.html, /服务器数据获取失败/)
    assert.match(ctx.html, /机器人/)
  })
}
test("malformed status data does not break either report", async () => {
  globalThis.fetch = async () => ({ok:true,status:200,json:async()=>({})})
  ctx.render = async (_name,data) => {ctx.html=data.html;return false}
  const e = event()
  await app.status(e)
  assert.match(ctx.html, /服务器状态数据格式无效/)
  assert.equal(typeof e.calls[0], "string")
  assert.match(e.calls[0], /服务器状态数据格式无效/)
})
test("offline heartbeat is not displayed as a healthy connected account", async () => {
  Bot["1"].stat.online = false
  const e = event()
  await app.status(e)
  assert.match(ctx.html, /账号已离线/)
  assert.doesNotMatch(ctx.html, /class="ok">已连接/)
})
test("missing heartbeat status is unknown, not online", async () => {
  Bot["1"].stat = {}
  const e = event()
  await app.status(e)
  assert.match(ctx.html, /已连接，在线状态未知/)
})
