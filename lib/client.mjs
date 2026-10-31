const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const numbers = (value, keys) => object(value) && keys.every(key => Number.isFinite(value[key]))

/** Validate the fields used by both renderers before accepting the response. */
export function validateHostStatus(snapshot) {
  const h = snapshot?.host
  const d = snapshot?.docker
  const valid =
    object(snapshot) && numbers(h, ["uptime", "cores", "cpuPercent"]) &&
    ["hostname", "os", "kernel"].every(key => typeof h[key] === "string") &&
    numbers(h.memory, ["used", "total", "available", "swapUsed", "swapTotal"]) &&
    Array.isArray(h.load) && h.load.length === 3 && h.load.every(Number.isFinite) &&
    Array.isArray(h.disks) && h.disks.every(row =>
      numbers(row, ["used", "total", "available"]) && typeof row.mount === "string" && typeof row.type === "string") &&
    (!d || (object(d) && typeof d.available === "boolean" &&
      (!d.available || (Array.isArray(d.df) && d.df.every(object) &&
        Array.isArray(d.containers) && d.containers.every(object))))) &&
    (snapshot.collectedAt === undefined || Number.isFinite(snapshot.collectedAt)) &&
    (snapshot.refreshSeconds === undefined || Number.isFinite(snapshot.refreshSeconds)) &&
    (snapshot.sampling === undefined || (object(snapshot.sampling) &&
      typeof snapshot.sampling.healthy === "boolean" &&
      numbers(snapshot.sampling, ["ageSeconds", "maxAgeSeconds"]))) &&
    (!d || d.errors === undefined || object(d.errors))
  if (!valid) throw new Error("服务器状态数据格式无效")
  return snapshot
}

/** Asks the host collector for one status snapshot. Throws an Error whose message is safe to show. */
export async function fetchHostStatus({ collectorUrl, token, timeoutMs = 10000 }, fetchImpl = fetch) {
  if (!collectorUrl) throw new Error("未配置采集器地址")
  if (!token) throw new Error("未配置采集器 token（环境变量 SYSTEM_STATUS_TOKEN）")
  let response
  try {
    response = await fetchImpl(new URL("/v1/status", collectorUrl), {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    throw new Error(error?.name === "TimeoutError" ? "采集器响应超时" : "连接不上采集器")
  }
  if (response.status === 401) throw new Error("采集器拒绝访问（token 不一致）")
  if (response.status === 503) throw new Error("采集器暂无有效数据（尚未采集成功或数据已过期）")
  if (!response.ok) throw new Error(`采集器返回错误 ${response.status}`)
  let snapshot
  try {
    snapshot = await response.json()
  } catch (error) {
    throw new Error(error?.name === "TimeoutError" || error?.name === "AbortError"
      ? "采集器响应超时" : "服务器状态响应不是有效 JSON")
  }
  return validateHostStatus(snapshot)
}
