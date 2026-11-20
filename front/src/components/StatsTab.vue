<template>
  <div class="card">
    <h2>团队总览</h2>
    <p class="small muted">团队账号资产与用量的统一视图：算力点余额、在线情况、模型可用覆盖率。</p>
    <div class="row" style="margin-top:10px"><button class="primary" @click="loadStats">刷新统计</button></div>
    <div class="kpi" style="margin-top:12px" v-html="kpi"></div>
  </div>
  <div class="card">
    <h2>成员维度</h2>
    <div style="margin-top:10px" v-html="membersHtml"></div>
  </div>
  <div class="card">
    <h2>账号维度</h2>
    <div style="margin-top:10px" v-html="accountsHtml"></div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api, ep } from '../api.js'
import { esc } from '../utils.js'

const kpi = ref(''), membersHtml = ref(''), accountsHtml = ref('')
async function loadStats() {
  const j = await api(ep.stats()), o = j.overview||{}
  kpi.value =
    `<div><b>${o.accounts||0}</b><span>账号总数</span></div>` +
    `<div><b>${o.vip_accounts||0}</b><span>VIP 账号</span></div>` +
    `<div><b>${o.free_accounts||0}</b><span>免费账号</span></div>` +
    `<div><b>${o.total_points??0}</b><span>算力点合计</span></div>` +
    `<div><b>${o.total_free_power??0}</b><span>每日免费算力</span></div>` +
    `<div><b>${o.alive_accounts||0}</b><span>在线账号</span></div>` +
    `<div><b>${o.invalid_accounts||0}</b><span>失效账号</span></div>` +
    `<div><b>${o.expiring_accounts||0}</b><span>临近到期</span></div>`
  const ms = j.members||[]
  if (!ms.length) membersHtml.value = '<p class="muted">暂无成员数据。</p>'
  else {
    let h = '<table><thead><tr><th>成员</th><th>团队</th><th>账号</th><th>算力点</th><th>今日额度</th><th>使用率</th><th>调用</th></tr></thead><tbody>'
    for (const m of ms) {
      const q = m.quota_unlimited?'<span class="muted">不限额</span>':`${m.quota_used}/${m.quota_limit}`
      const pct = m.quota_unlimited?'':`<div class="quota-bar"><div style="width:${Math.min(100,m.quota_percent||0)}%"></div></div><span class="small muted">${m.quota_percent||0}%</span>`
      h += `<tr><td>${esc(m.name)}${m.note?`<div class="small muted">${esc(m.note)}</div>`:''}</td><td>${esc(m.team_name||'-')}</td><td>${esc(m.accounts??0)}</td><td>${esc(m.points??0)}</td><td>${q}</td><td>${pct}</td><td>${esc(m.request_count??0)}</td></tr>`
    }
    membersHtml.value = h + '</tbody></table>'
  }
  const as = j.accounts||[]
  if (!as.length) accountsHtml.value = '<p class="muted">暂无账号数据。</p>'
  else {
    let h = '<table><thead><tr><th>账号</th><th>成员</th><th>类型</th><th>算力点</th><th>免费算力</th><th>可用模型</th><th>调用/错误</th><th>到期</th></tr></thead><tbody>'
    for (const a of as) {
      const ex = a.days_left==null?'<span class="muted">-</span>':(a.days_left<0?`<span class="badge b-dead">已到期</span>`:`<span class="badge ${a.days_left<=30?'b-warn':'b-free'}">${a.days_left}天</span>`)
      h += `<tr><td>${esc(a.nickname||a.account)}${a.note?`<div class="small muted">${esc(a.note)}</div>`:''}</td><td>${esc(a.member_name||'-')}</td><td>${a.account_type==='member'?'VIP':a.account_type==='free'?'免费':'未知'}</td><td>${esc(a.points??0)}</td><td>${esc(a.free_power??0)}</td><td>${esc(a.model_usable_count??0)}/${esc(a.model_total_count??0)}</td><td>${esc(a.request_count??0)}/${esc(a.error_count??0)}</td><td>${ex}</td></tr>`
    }
    accountsHtml.value = h + '</tbody></table>'
  }
}
onMounted(loadStats)
</script>
