import { reactive } from 'vue'
import { getToken, setUnauthorizedHandler, setErrorNotifier } from './api.js'

export const store = reactive({
  tab: 'accounts',
  who: '',
  health: '',
  loginShow: false,
  // 是否已具备访问后端数据的条件（已登录且条款已接受）。
  // 未就绪时不渲染页签组件，避免组件挂载时在未登录态发出 401 请求；
  // 登录成功后置 true，组件才挂载并在 onMounted 里正常加载数据。
  ready: false,
  toast: { show: false, msg: '', ok: true, timer: null },
  expiryBell: 0,
})

export function toast(msg, ok = true) {
  const t = store.toast
  t.msg = msg
  t.ok = ok
  t.show = true
  if (t.timer) clearTimeout(t.timer)
  t.timer = setTimeout(() => { t.show = false }, 3500)
}

export function showLogin() { store.loginShow = true }
export function afterLogin(user) {
  store.who = '@' + user
}

// 把 api 层的两个回调接进来：仅 401 跳登录；错误统一 toast。
setUnauthorizedHandler(() => { store.ready = false; showLogin() })
setErrorNotifier(msg => toast(msg, false))

export function hasToken() { return !!getToken() }
