<template>
  <div class="card">
    <h2>模型可用性（按账号识别，免费版用不了的会标红）</h2>
    <div class="row">
      <div><label>账号</label><select v-model="account"><option v-for="a in accounts" :key="a.account" :value="a.account">{{ a.account }}（{{ a.account_type_label||a.account_type||'?' }}{{ a.is_member?'·VIP':'' }}）</option></select></div>
      <div><label>类型</label><select v-model="kind"><option value="all">全部</option><option value="video">视频</option><option value="image">图片</option></select></div>
      <div><label>&nbsp;</label><button class="primary" @click="loadModels">查询</button></div>
      <div><label>&nbsp;</label><label><input type="checkbox" v-model="usableOnly"> 只看可用</label></div>
    </div>
    <div class="small muted" style="margin:8px 0" v-html="info"></div>
    <div class="grid">
      <div v-for="m in models" :key="m.model_key||m.name" class="model">
        <img v-if="cover(m)" :src="cover(m)" @error="e=>e.target.style.display='none'">
        <div class="nm">{{ m.name||'-' }} <span class="badge" :class="m.usable?'b-ok':'b-no'">{{ m.usable?'可用':'不可用' }}</span></div>
        <div class="meta">{{ m.kind||'-' }} · {{ m.category||'' }} <span v-if="m.requires_membership" class="tag">会员专属</span><br>key: {{ m.model_key||'-' }}</div>
        <div><span v-for="l in (m.labels||[])" :key="l" class="tag">{{ l }}</span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api, ep } from '../api.js'
import { safeUrl, esc } from '../utils.js'

const accounts = ref([]), account = ref(''), kind = ref('all'), usableOnly = ref(false)
const info = ref(''), models = ref([])

function cover(m) { return safeUrl(m.cover_url) }

async function loadAccounts() {
  const j = await api(ep.accounts())
  accounts.value = j.accounts||[]
  if (!account.value && accounts.value.length) account.value = accounts.value[0].account
}
async function loadModels() {
  if (!account.value) return
  const j = await api(ep.accountModels(account.value, kind.value, usableOnly.value))
  info.value = `账号类型：<b>${esc(j.account_type||'-')}</b> · 模型 ${esc(j.count??0)} 个 · 当日免费权益模型：${(j.free_benefit_keys||[]).map(x=>esc(x)).join(', ')||'无'}`
  models.value = j.models||[]
}
onMounted(() => loadAccounts().then(loadModels))
</script>
