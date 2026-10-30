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
  if (!response.ok) throw new Error(`采集器返回错误 ${response.status}`)
  return response.json()
}
