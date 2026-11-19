<template>
  <!-- 使用条例与合规声明闸门 -->
  <div v-if="termsShow" class="overlay" style="z-index:120">
    <div class="login-card" style="width:640px;max-width:94vw">
      <h1>{{ terms.title || '使用条例与合规声明' }}</h1>
      <p class="small muted" style="margin:2px 0 10px">首次使用需阅读至底部并勾选同意；同意状态记录在本机 settings.json。</p>
      <div class="terms-box" @scroll="termsScrolled" v-html="termsHtml"></div>
      <p class="terms-tip">{{ termsTip }}</p>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:var(--txt)">
        <input type="checkbox" v-model="termsAgree" @change="termsCheck"> 我已阅读并同意上述使用条例与合规声明
      </label>
      <button class="primary" style="width:100%;margin-top:12px" :disabled="!canAcceptTerms" @click="acceptTerms">同意并进入面板</button>
      <button v-if="termsAccepted" class="ghost" style="width:100%;margin-top:8px" @click="closeTerms">关闭（已同意，无需重复操作）</button>
    </div>
  </div>

  <!-- 管理员登录遮罩 -->
  <div v-if="store.loginShow" class="overlay">
    <div class="login-card">
      <h1>LibTV-Team</h1>
      <p class="small muted">团队账号统一管理面板 · 管理员登录（单管理员）</p>
      <label>用户名</label>
      <input v-model="lgUser" autocomplete="username">
      <label>密码</label>
      <input v-model="lgPass" type="password" autocomplete="current-password" @keydown.enter="doAdminLogin">
      <button class="primary" style="width:100%;margin-top:6px" @click="doAdminLogin">登录</button>
      <p class="small" style="color:var(--bad);min-height:16px">{{ lgErr }}</p>
      <p class="small muted">默认账号 admin / admin，首次登录后请到「设置」修改密码。</p>
    </div>
  </div>

  <header>
    <h1>LibTV-Team</h1><span class="ver">团队账号统一管理面板 · v0.6.0</span>
    <span class="ver" id="health">{{ store.health }}</span>
    <span class="bell" @click="go('accounts')" title="会员到期提醒">
      <template v-if="store.expiryBell">🔔 <b>{{ store.expiryBell }}</b></template>
    </span>
    <span style="flex:1"></span>
    <span class="ver" id="who">{{ store.who }}</span>
    <button class="ghost" style="padding:6px 10px" @click="logout">退出</button>
  </header>
  <nav>
    <button v-for="t in tabs" :key="t.key" :class="{ active: store.tab === t.key }" @click="go(t.key)">{{ t.label }}</button>
  </nav>
  <main>
    <component v-if="store.ready" :is="currentComponent" :key="store.tab" @expiry-count="n => store.expiryBell = n" />
  </main>

  <footer style="text-align:center;color:var(--mut);font-size:12px;padding:18px 22px;border-top:1px solid var(--line)">
    合规声明与使用条例：本工具面向团队自用，用于统一管理团队成员各自合法拥有的 liblib 账号；遵守平台服务条款，不做逆向、破解、绕过平台限制、批量注册与账号买卖；凭据仅存本机，作者与维护者对不当使用或账号受限造成的后果不承担责任。
  </footer>

  <div v-if="store.toast.show" class="toast" :style="store.toast.ok ? {} : { borderColor: 'var(--bad)' }">{{ store.toast.msg }}</div>
</template>

<script setup>
import { computed, onMounted, ref, nextTick } from 'vue'
import { api, adminLogin, setToken, clearToken, ep, API } from './api.js'
import { store, toast, showLogin, afterLogin, hasToken } from './store.js'
import { esc } from './utils.js'
import AccountsTab from './components/AccountsTab.vue'
import TeamsTab from './components/TeamsTab.vue'
import LoginTab from './components/LoginTab.vue'
import ModelsTab from './components/ModelsTab.vue'
import PlaygroundTab from './components/PlaygroundTab.vue'
import BalanceTab from './components/BalanceTab.vue'
import MonitorTab from './components/MonitorTab.vue'
import StatsTab from './components/StatsTab.vue'
import NotifyTab from './components/NotifyTab.vue'
import SettingsTab from './components/SettingsTab.vue'

const tabs = [
  { key: 'accounts', label: '账号池' },
  { key: 'teams', label: '团队与成员' },
  { key: 'login', label: '登录' },
  { key: 'models', label: '模型可用性' },
  { key: 'playground', label: 'Playground' },
  { key: 'balance', label: '算力均摊' },
  { key: 'monitor', label: '活性监控' },
  { key: 'stats', label: '团队统计' },
  { key: 'notify', label: '通知告警' },
  { key: 'settings', label: '设置' },
]
const compMap = {
  accounts: AccountsTab, teams: TeamsTab, login: LoginTab, models: ModelsTab,
  playground: PlaygroundTab, balance: BalanceTab, monitor: MonitorTab,
  stats: StatsTab, notify: NotifyTab, settings: SettingsTab,
}
const currentComponent = computed(() => compMap[store.tab] || AccountsTab)

function go(name) {
  store.tab = name
  if (name === 'accounts') loadHealth()
}
async function loadHealth() {
  try { const h = await api(ep.accounts()); store.health = '· 账号 ' + h.accounts.length + ' 个' } catch (e) { /* ignore */ }
}

const lgUser = ref('admin'), lgPass = ref('admin'), lgErr = ref('')
async function doAdminLogin() {
  lgErr.value = ''
  try {
    const r = await adminLogin(lgUser.value, lgPass.value)
    const d = await r.json().catch(() => null)
    if (!r.ok) { lgErr.value = (d && d.detail) || '登录失败'; return }
    setToken(d.token)
    store.loginShow = false
    afterLogin(d.user)
    store.ready = true
    if (d.needs_change) toast('请尽快在「设置」修改默认密码')
    loadHealth()
  } catch (e) { lgErr.value = '网络错误' }
}
function logout() {
  clearToken(); store.who = ''; store.health = ''; store.ready = false; store.expiryBell = 0; showLogin()
}

// ---- 条款闸门 ----
const termsShow = ref(false)
const terms = ref({})
const termsHtml = ref('加载中…')
const termsTip = ref('请滚动阅读完整条款后，方可勾选同意。')
const termsAgree = ref(false)
const termsAccepted = ref(false)
const termsRead = ref(false)
const canAcceptTerms = computed(() => termsRead.value && termsAgree.value)

async function loadTerms() {
  try {
    const r = await fetch(API + ep.terms())
    const j = await r.json()
    terms.value = j
    termsHtml.value = String(j.text || '').split('\n').filter(x => x.trim()).map(x => `<p>${esc(x)}</p>`).join('')
    termsAccepted.value = !!j.accepted
    termsRead.value = false; termsAgree.value = false; canAcceptTerms.value
    termsTip.value = '请滚动阅读完整条款后，方可勾选同意。'
    await nextTick()
    const el = document.querySelector('.terms-box')
    if (el && el.scrollHeight <= el.clientHeight + 8) {
      termsRead.value = true
      termsTip.value = '已阅读完整条款，可以勾选同意。'
    }
    return j
  } catch (e) {
    termsHtml.value = '<p style="color:var(--bad)">使用条例加载失败，请检查服务是否正常。</p>'
    return null
  }
}
function termsScrolled(e) {
  const el = e.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 8) {
    termsRead.value = true
    termsTip.value = '已阅读完整条款，可以勾选同意。'
  }
}
function termsCheck() { /* v-model + computed 已处理 */ }
async function acceptTerms() {
  if (!termsRead.value || !termsAgree.value) return toast('请先阅读完整条款并勾选同意', false)
  try {
    const r = await fetch(API + ep.termsAccept(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
    })
    if (!r.ok) { toast('记录同意状态失败', false); return }
    termsShow.value = false
    toast('已同意使用条例')
    if (hasToken()) { store.loginShow = false; store.ready = true; loadHealth() } else showLogin()
  } catch (e) { toast('网络错误', false) }
}
function closeTerms() {
  termsShow.value = false
  if (hasToken()) { store.loginShow = false; store.ready = true }
  else showLogin()
}
function showTerms() {
  store.loginShow = false
  termsShow.value = true
  loadTerms().then(j => { termsAccepted.value = !!(j && j.accepted) })
}

// 供子组件「查看完整使用条例」调用
import { provide } from 'vue'
provide('showTerms', showTerms)

onMounted(async () => {
  const t = await loadTerms()
  if (t && t.need_accept) {
    termsShow.value = true
    store.loginShow = false
    return
  }
  termsShow.value = false
  if (hasToken()) { store.ready = true; loadHealth() }
  else showLogin()
})
</script>
