export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]))
}
// 媒体地址只允许 http(s) / data:image / 站内相对路径
export function safeUrl(u) {
  const s = String(u == null ? '' : u)
  return /^(https?:\/\/|data:image\/|\/)/i.test(s) ? s : ''
}
export function expiryCls(level) {
  return level === 'critical' || level === 'expired' ? 'e-critical'
    : level === 'warning' ? 'e-warning' : level === 'ok' ? 'e-ok' : 'e-unknown'
}
export function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '未'
}
