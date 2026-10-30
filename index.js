// TRSS-Yunzai adapter. This is the only file that knows about TRSS; everything in lib/ is framework-free.
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import cfg from "../../lib/config/config.js"
import PluginsLoader from "../../lib/plugins/loader.js"
import Renderer from "../../lib/renderer/loader.js"
import { COMMAND_REG } from "./lib/command.mjs"
import { loadConfig } from "./lib/config.mjs"
import { fetchHostStatus } from "./lib/client.mjs"
import { formatReport } from "./lib/format.mjs"
import { buildHtml } from "./lib/html.mjs"

const ROOT = path.dirname(fileURLToPath(import.meta.url))
// A fixed one-line template ({{@ html}}); the page itself is built by lib/html.mjs on every request.
const TEMPLATE = path.join(ROOT, "resources", "status.html")
const PLUGINS_DIR = path.dirname(ROOT)
const BUILTIN_TITLES = { system: "TRSS 系统功能", other: "TRSS 辅助功能" }

const readJSON = file => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"))
  } catch {
    return {}
  }
}

/** Plugin directories that actually loaded, titled from their own plugin.manifest.json when they have one. */
function loadedPlugins() {
  const dirs = new Set()
  for (const [name, count] of PluginsLoader.pluginCountMap ?? []) if (count > 0) dirs.add(String(name).split("/")[0])
  return [...dirs].sort().map(dir => {
    const root = path.join(PLUGINS_DIR, dir)
    const manifest = readJSON(path.join(root, "plugin.manifest.json"))
    const pkg = readJSON(path.join(root, "package.json"))
    return { title: manifest.title || BUILTIN_TITLES[dir] || dir, version: manifest.version || pkg.version || "" }
  })
}

function botSnapshot() {
  const accounts = []
  for (const id of Bot.uin ?? []) {
    const bot = Bot[id]
    if (!bot || id === "stdin") continue
    const received = bot.stat?.recv_msg_cnt
    accounts.push({
      id: String(id),
      nickname: bot.nickname || "",
      adapter: bot.adapter?.name || "",
      ...(typeof received === "number" ? { received, sent: bot.stat?.sent_msg_cnt ?? 0 } : {}),
    })
  }
  return {
    framework: { name: "TRSS-Yunzai", version: cfg.package?.version || "未知" },
    node: process.version,
    uptime: process.uptime(),
    rss: process.memoryUsage().rss,
    accounts,
    plugins: loadedPlugins(),
  }
}

export class SystemStatus extends plugin {
  constructor() {
    super({
      name: "系统状态",
      dsc: "#系统状态：服务器、Docker、机器人与插件状态（仅主人）",
      event: "message",
      priority: 5000,
      rule: [{ reg: COMMAND_REG, fnc: "status", permission: "master" }],
    })
  }

  async status(e) {
    const config = loadConfig(ROOT)
    let host
    let hostError
    try {
      host = await fetchHostStatus(config)
    } catch (error) {
      hostError = error.message
    }
    const report = { host, hostError, bot: botSnapshot(), timeZone: config.timeZone }
    let image
    try {
      // TRSS screenshots the page with its own Chromium (puppeteer, falling back to its other renderers).
      image = await Renderer.render("SystemStatus-Plugin/status", {
        tplFile: TEMPLATE,
        saveId: "status",
        imgType: "png",
        html: buildHtml(report),
      })
    } catch (error) {
      logger.error("[系统状态] 图片生成失败，改发文字", error)
    }
    await e.reply(image ? segment.image(image) : formatReport(report))
    return true
  }
}

export const apps = { SystemStatus }
