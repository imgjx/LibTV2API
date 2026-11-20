// API 契约层：所有路径与旧版 panel.html 完全一致（基址 /api/v1）。
// 这里是"API 路径没变"的唯一真源，组件只调用这些封装，不自行拼路径。
export const API = '/api/v1'

const TOKEN_KEY = 'liblib_token'
export function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }
export function setToken(t) { localStorage.setItem(TOKEN_KEY, t) }
export function clearToken() { localStorage.removeItem(TOKEN_KEY) }

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

// 统一错误提示回调（由 App 注入 toast）
let notifyError = () => {}
export function setErrorNotifier(fn) { notifyError = fn }

// 与旧版 api() 语义一致：仅 401 触发管理员会话失效；账号级过期是 409，只提示不登出。
export async function api(path, opt = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const t = getToken()
  if (t) headers['Authorization'] = 'Bearer ' + t
  const r = await fetch(API + path, Object.assign({ headers }, opt))
  let j = null
  try { j = await r.json() } catch (e) { /* no body */ }
  if (r.status === 401) { onUnauthorized(); throw new Error('unauthorized') }
  if (!r.ok) {
    const d = j && j.detail
    const msg = (d && (typeof d === 'object' ? (d.message || d.error || JSON.stringify(d)) : d)) || (j && j.error) || ('HTTP ' + r.status)
    notifyError(msg)
    const err = new Error('api err')
    err.apiMessage = msg
    throw err
  }
  return j
}

// 需要原始 Response 的场景（导出下载二进制、blob）
export async function apiRaw(path, opt = {}) {
  const headers = {}
  const t = getToken()
  if (t) headers['Authorization'] = 'Bearer ' + t
  return fetch(API + path, Object.assign({ headers }, opt))
}

// 管理员登录不走 Bearer（用账号密码换取 token）
export async function adminLogin(username, password) {
  return fetch(API + '/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

// ==== 下列即旧面板全部端点，路径逐字对应 ====
export const ep = {
  accounts: () => '/accounts',
  accountsExport: () => '/accounts/export',
  accountsExpiring: (days) => `/accounts/expiring?days=${days}`,
  accountsImport: () => '/accounts/import',
  syncAll: () => '/accounts/sync-all',
  accountSync: (a) => `/accounts/${encodeURIComponent(a)}/sync`,
  claimAll: () => '/accounts/claim-all',
  accountAssign: (a) => `/accounts/${encodeURIComponent(a)}/assign`,
  accountRemark: (a) => `/accounts/${encodeURIComponent(a)}/remark`,
  accountDelete: (a) => `/accounts/${encodeURIComponent(a)}`,
  accountProxy: (a) => `/accounts/${encodeURIComponent(a)}/proxy`,
  accountModels: (a, kind, usableOnly) => `/accounts/${encodeURIComponent(a)}/models?kind=${encodeURIComponent(kind)}&usable_only=${usableOnly}`,

  teams: () => '/teams',
  teamDelete: (id) => `/teams/${id}`,
  teamMembers: (teamId) => `/teams/${teamId}/members`,
  members: () => '/members',
  memberQuota: (id) => `/members/${id}/quota`,
  memberDelete: (id) => `/members/${id}`,

  phoneSendCode: () => '/auth/phone/send-code',
  phoneLogin: () => '/auth/phone/login',
  cookieLogin: () => '/auth/cookie/login',
  wechatAuthorize: () => '/auth/wechat/authorize?open_browser=false',
  wechatQr: (state) => `/auth/wechat/qr?state=${encodeURIComponent(state)}`,
  wechatPoll: (state) => `/auth/wechat/poll?state=${encodeURIComponent(state)}`,

  adminPassword: () => '/admin/password',
  adminApikey: () => '/admin/apikey',
  settings: () => '/settings',

  monitorStatus: () => '/monitor/status',
  monitorCheck: () => '/monitor/check',
  stats: () => '/stats',

  tools: (kind) => `/tools?kind=${encodeURIComponent(kind)}`,
  generate: (kind) => `/generate/${kind}`,
  videoBalance: () => '/generate/video/balance',

  notifyStatus: () => '/notify/status',
  notifyConfig: () => '/notify/config',
  notifyRule: (event) => `/notify/rule/${event}`,
  notifyTest: () => '/notify/test',
  alertsScan: () => '/alerts/scan',

  terms: () => '/terms',
  termsAccept: () => '/terms/accept',
}
