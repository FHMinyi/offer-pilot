// 设备归属标识（里程碑一：归属标签，非鉴权）。
// 与后端 deps.get_current_user 的 X-Device-Id 接缝配套：所有 /api 请求经 apiFetch
// 自动带上本头；缺失/隐私模式回退 'local'（与后端缺省一致）。里程碑三接真账号后，
// 此值由真实登录态取代，前端契约不变。

const KEY = 'op.device.id'

/** 取（或首次生成并持久化）设备 id；localStorage 不可用时回退 'local'。 */
export function getDeviceId(): string {
  try {
    let id = localStorage.getItem(KEY)
    if (!id) {
      id =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `dev-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
      localStorage.setItem(KEY, id)
    }
    return id
  } catch {
    // 隐私模式 / 非浏览器环境：回退与后端缺省一致的 'local'
    return 'local'
  }
}

/** 归属请求头（不含 Content-Type，保 FormData 安全）。 */
export function deviceHeaders(): Record<string, string> {
  return { 'X-Device-Id': getDeviceId() }
}
