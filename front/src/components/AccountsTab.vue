<template>
  <!-- 会员到期提醒 -->
  <div class="card">
    <h2>会员到期提醒 <span class="small muted" id="expirySummary">{{ expirySummary }}</span></h2>
    <p class="small muted">平台原生没有团队功能，成员账号到期时间互不相通，这里统一盯梢：临近到期提前提醒，避免团队额度突然断档。</p>
    <div style="margin-top:10px">
      <p v-if="!expiry.count" class="muted small">近期没有账号的会员即将到期。</p>
      <table v-else>
        <thead><tr><th>账号</th><th>团队 / 成员</th><th>备注</th><th>会员到期</th><th>剩余</th><th>积分</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="it in expiry.items" :key="it.account">
            <td>{{ it.account }}</td>
            <td class="small">{{ it.team_name||'-' }}<template v-if="it.member_display_name"> · {{ it.member_display_name }}</template></td>
            <td class="small">{{ it.remark||'-' }}</td>
            <td class="small">{{ it.member_until_text||it.member_until||'-' }}</td>
            <td><span class="expiry" :class="expiryCls(it.level)">{{ it.days_left<0 ? `已过期 ${-it.days_left} 天` : `剩 ${it.days_left} 天` }}</span></td>
            <td>{{ it.points??'-' }}</td>
            <td><button class="danger" @click="syncOne(it.account)">刷新</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>账号池（团队成员会员 / 额度包）</h2>
    <div class="row" style="margin-bottom:12px">
      <button class="primary" @click="loadAccounts">刷新</button>
      <button class="ghost" @click="showImport = !showImport">导入 JSON</button>
      <button class="ghost" @click="exportAccounts">导出 JSON</button>
      <button class="ghost" @click="syncAll">全部同步</button>
      <button class="ghost" @click="claimAll">全部领取权益</button>
    </div>
    <div v-if="showImport" class="card" style="background:var(--panel2)">
      <label>账号 JSON（含 accounts 数组）或粘贴 raw 文本</label>
      <textarea v-model="importText" rows="5" style="width:100%"></textarea>
      <div class="row" style="margin-top:8px"><button class="primary" @click="importAccounts">导入并自动识别类型</button></div>
    </div>
    <div>
      <p v-if="!list.length" class="muted">暂无账号。点「手机号登录 / 微信扫码 / Cookie / 导入」添加，登录后会自动识别类型。</p>
      <table v-else>
        <thead><tr><th>账号</th><th>类型</th><th>团队 / 成员</th><th>备注</th><th>积分</th><th>免费算力</th><th>额度</th><th>会员到期</th><th>登录令牌</th><th>活性</th><th>可用模型</th><th>权益</th><th>代理</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="a in list" :key="a.account">
            <td>{{ a.account }}<span v-if="a.is_sub" class="badge b-sub">副卡</span></td>
            <td><span class="badge" :class="a.account_type==='member'?'b-member':'b-free'">{{ typeLabel(a) }}</span></td>
            <td>{{ a.team_name ? (a.team_name + (a.member_display_name?' · '+a.member_display_name:'')) : (a.member_display_name||'未分配') }}</td>
            <td class="small">{{ a.remark||'—' }}</td>
            <td>{{ a.points??'-' }}</td>
            <td>{{ a.free_power??'-' }}</td>
            <td>
              <template v-if="a.quota">
                <span v-if="a.quota.unlimited" class="muted">不限</span>
                <div v-else style="min-width:110px">
                  <div class="small">{{ a.quota.used??0 }} / {{ a.quota.limit }} 点</div>
                  <div class="quota-bar"><i :class="quotaCls(a.quota)" :style="{width: quotaPct(a.quota)+'%'}"></i></div>
                </div>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td><span class="expiry" :class="expiryCls(a.member_expiry_level)" :title="a.member_until_text||''">{{ expiryText(a) }}</span></td>
            <td><span class="expiry" :class="tokenCls(a)" :title="tokenTip(a)">{{ tokenText(a) }}</span></td>
            <td>
              <span v-if="a.auth_expired" class="badge b-warn" title="登录态已过期，账号本身未受限，重新获取 token 即可继续使用">登录态过期</span>
              <span v-else-if="a.alive===true" class="badge b-alive">在线</span>
              <span v-else-if="a.alive===false" class="badge b-dead">异常</span>
              <span v-else class="badge b-free">未检</span>
            </td>
            <td>{{ a.model_usable_count??0 }}/{{ a.model_total_count??0 }}</td>
            <td class="small">{{ a.last_claim||'-' }}</td>
            <td>{{ a.proxy ? a.proxy.slice(0,18)+'…' : '-' }}</td>
            <td>
              <button class="danger" @click="assignAccount(a.account)">分配</button>
              <button class="danger" @click="editRemark(a.account)">备注</button>
              <button class="danger" @click="setProxy(a.account)">代理</button>
              <button class="danger" @click="syncOne(a.account)">同步</button>
              <button v-if="a.auth_expired" class="primary" @click="relogin(a.account)">重新登录</button>
              <button class="danger" @click="del(a.account)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 分配账号弹窗 -->
  <div v-if="pickShow" class="overlay">
    <div class="login-card">
      <h1>分配账号</h1>
      <p class="small muted">账号：{{ pickAccount }}</p>
      <label>选择成员（不选表示解除归属）</label>
      <select v-model="pickMember" style="width:100%;margin-bottom:12px">
        <option value="">（不分配）</option>
        <optgroup v-for="t in pickTeams" :key="t.id" :label="t.name">
          <option v-for="m in pickMembers.filter(mm=>mm.team_id===t.id)" :key="m.id" :value="m.id">{{ t.name }} · {{ m.name }}</option>
        </optgroup>
      </select>
      <button class="primary" style="width:100%" @click="confirmAssign">确定</button>
      <button class="ghost" style="width:100%;margin-top:8px" @click="pickShow=false">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { api, apiRaw, getToken, ep } from '../api.js'
import { toast, store } from '../store.js'
import { expiryCls } from '../utils.js'

const list = ref([])
const expiry = ref({ count: 0, items: [] })
const expirySummary = ref('')
const showImport = ref(false)
const importText = ref('')

function typeLabel(a) {
  return a.account_type_label || (a.account_type==='member'?'VIP':a.account_type==='free'?'免费':'未知')
}
function quotaPct(q) { return Math.min(100, Math.round((q.used||0)/(q.limit||1)*100)) }
function quotaCls(q) { const p=quotaPct(q); return p>=100?'bad':p>=80?'warn':'' }
function expiryText(a) {
  if (a.member_until_days==null) return '—'
  return a.member_until_days<0 ? `已过期 ${-a.member_until_days} 天` : `剩 ${a.member_until_days} 天`
}
function tokenCls(a) {
  if (a.token_has_expiry) return expiryCls(a.token_level)
  return 'e-unknown'
}
function tokenText(a) {
  return a.token_has_expiry ? (a.token_text||'—') : (a.token_online_text||'—')
}
function tokenTip(a) {
  if (a.token_has_expiry) {
    return (a.token_expires_at_text?('预计到期：'+a.token_expires_at_text):'')
      + (a.token_level==='critical'?'；请尽快重新登录':'')
      + (a.token_level==='expired'?'；令牌已过期，请重新登录':'')
      + (a.token_online_text?('；'+a.token_online_text):'')
  }
  return (a.token_issued_at_text?('登录于：'+a.token_issued_at_text):'')
    + (a.token_online_text?('；'+a.token_online_text):'')
    + '；平台未返回令牌到期时间，是否失效以真实请求判定'
}

async function loadAccounts() { try { const j = await api(ep.accounts()); list.value = j.accounts||[] } catch(e){} }
async function loadExpiry() {
  let j; try { j = await api(ep.accountsExpiring(60)) } catch(e) { return }
  const n = j.count||0
  expiry.value = { count: n, items: j.items||[] }
  expirySummary.value = n ? `（${n} 个账号需要关注）` : '（暂无临近到期的账号）'
  store.expiryBell = n
}
async function exportAccounts() {
  const r = await apiRaw(ep.accountsExport())
  if (!r.ok) { toast('导出失败：HTTP '+r.status, false); return }
  const b = await r.blob(), u = URL.createObjectURL(b), a = document.createElement('a')
  a.href = u; a.download = 'liblib-accounts.json'; a.click()
  setTimeout(()=>URL.revokeObjectURL(u), 1000); toast('已导出')
}
async function importAccounts() {
  await api(ep.accountsImport(), { method:'POST', body:JSON.stringify({ raw: importText.value }) })
  toast('导入完成，已自动识别类型'); importText.value=''; showImport.value=false; loadAccounts()
}
async function syncAll() { try { await api(ep.syncAll(), { method:'POST' }); toast('已同步全部') } finally { loadAccounts() } }
async function syncOne(a) { try { await api(ep.accountSync(a), { method:'POST' }); toast('已同步 '+a) } finally { loadAccounts(); loadExpiry() } }
async function claimAll() { await api(ep.claimAll(), { method:'POST' }); toast('权益领取完成') }

const showTerms = inject('showTerms', ()=>{})
function relogin(acc) { store.tab='login'; toast('请获取验证码并完成登录，以刷新该账号的登录态'); window.__prefillPhone = acc }

// 分配
const pickShow = ref(false), pickAccount = ref(''), pickMember = ref('')
const pickTeams = ref([]), pickMembers = ref([])
async function assignAccount(account) {
  const t = await api(ep.teams()), m = await api(ep.members())
  pickTeams.value = t.teams||[]; pickMembers.value = m.members||[]
  if (!pickTeams.value.length) return toast('请先创建团队并添加成员', false)
  const cur = (pickMembers.value.find(mm=>(mm.account_ids||[]).includes(account))||{}).id||''
  pickMember.value = cur; pickAccount.value = account; pickShow.value = true
}
async function confirmAssign() {
  const memberId = pickMember.value||null
  pickShow.value = false
  const note = window.prompt('备注（留空则自动生成「团队·成员 的账号」）','')
  if (note===null) return
  await api(ep.accountAssign(pickAccount.value), { method:'POST', body:JSON.stringify({ member_id:memberId, remark:note===''?undefined:note }) })
  toast('已分配'); loadAccounts()
}
async function editRemark(account) {
  const j = await api(ep.accounts()), a = j.accounts.find(x=>x.account===account)
  const v = window.prompt('设置备注', a?(a.remark||''):'')
  if (v===null) return
  await api(ep.accountRemark(account), { method:'POST', body:JSON.stringify({ remark:v }) })
  toast('备注已更新'); loadAccounts()
}
async function del(acc) {
  if (!window.confirm('删除账号 '+acc+' ?')) return
  await api(ep.accountDelete(acc), { method:'DELETE' }); toast('已删除'); loadAccounts()
}
async function setProxy(acc) {
  const j = await api(ep.accounts())
  const p = window.prompt('设置代理（留空清除）', j.accounts.find(x=>x.account===acc)?.proxy||'')
  await api(ep.accountProxy(acc), { method:'POST', body:JSON.stringify({ proxy:p||null }) })
  toast('代理已更新'); loadAccounts()
}

onMounted(() => { loadAccounts(); loadExpiry() })
</script>
