import fs from "node:fs"
import path from "node:path"

const readJSON = file => {
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"))
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("expected an object")
    return value
  } catch (error) {
    if (error.code === "ENOENT") return {}
    throw new Error(`配置文件无法解析：${path.basename(file)}`)
  }
}

/** defaults.json ships with the plugin; config.json (optional, not in Git) overrides it. */
export function loadConfig(root, env = process.env) {
  const config = {
    ...readJSON(path.join(root, "config", "defaults.json")),
    ...readJSON(path.join(root, "config", "config.json")),
  }
  let url
  try {
    url = new URL(config.collectorUrl)
  } catch {
    throw new Error("采集器地址无效")
  }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("采集器地址必须使用 HTTP 或 HTTPS")
  if (!Number.isInteger(config.timeoutMs) || config.timeoutMs < 1000 || config.timeoutMs > 60000)
    throw new Error("等待上限必须是 1000～60000 毫秒的整数")
  if (typeof config.tokenEnv !== "string" || !config.tokenEnv.trim()) throw new Error("token 环境变量名无效")
  if (typeof config.timeZone !== "string" || !config.timeZone.trim()) throw new Error("显示时区无效")
  try {
    new Intl.DateTimeFormat("en", { timeZone: config.timeZone }).format()
  } catch {
    throw new Error("显示时区无效")
  }
  // The token never lives in a plugin file: it comes from the container environment.
  config.token = env[config.tokenEnv || "SYSTEM_STATUS_TOKEN"] || ""
  return config
}
