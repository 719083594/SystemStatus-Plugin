import fs from "node:fs"
import path from "node:path"

const readJSON = file => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"))
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
  // The token never lives in a plugin file: it comes from the container environment.
  config.token = env[config.tokenEnv || "SYSTEM_STATUS_TOKEN"] || ""
  return config
}
