<template>
  <div class="card">
    <h2>设置（OpenAI 兼容 API / 每积分消耗 / 监控间隔）</h2>
    <p class="small muted">OpenAI 兼容 API 用于「视频拆分」的创意拆条（任意兼容 /v1/chat/completions 的服务：OpenAI、DeepSeek、通义、本地 Ollama 等）。密钥仅保存在本机 settings.json（权限 0600）。</p>
    <div class="row">
      <div style="flex:1;min-width:280px"><label>Base URL</label><input v-model="base" style="width:100%" placeholder="https://api.openai.com/v1"></div>
      <div><label>模型</label><input v-model="model" placeholder="gpt-4o-mini" style="width:160px"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div style="flex:1;min-width:280px"><label>API Key</label><input v-model="key" type="password" style="width:100%" placeholder="sk-...（留空=不修改/使用已存）"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>每积分消耗(点/秒)</label><input v-model.number="pps" type="number" style="width:120px"></div>
      <div><label>监控间隔(秒)</label><input v-model.number="interval" type="number" style="width:120px"></div>
      <div><label>&nbsp;</label><button class="primary" @click="saveSettings">保存设置</button></div>
      <div><label>&nbsp;</label><button class="ghost" @click="loadSettings">读取当前</button></div>
    </div>
    <div class="small muted" style="margin-top:8px">{{ box }}</div>
  </div>

  <div class="card">
    <h2>管理员与访问（单管理员 · 公网部署请务必开启鉴权）</h2>
    <div class="small muted" v-html="adminBox"></div>
    <div class="row" style="margin-top:10px">
      <div style="flex:1;min-width:200px"><label>旧密码</label><input v-model="pwOld" type="password" style="width:100%" placeholder="当前密码" autocomplete="current-password"></div>
      <div style="flex:1;min-width:200px"><label>新密码</label><input v-model="pwNew" type="password" style="width:100%" placeholder="新密码" autocomplete="new-password"></div>
      <div><label>&nbsp;</label><button class="primary" @click="changePassword">修改密码</button></div>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="ghost" @click="showApiKey">显示对外 API Key</button>
      <button class="ghost" @click="regenApiKey">重置 API Key</button>
    </div>
    <div class="small muted" style="margin-top:8px" v-html="apikeyBox"></div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api, ep, clearToken } from '../api.js'
import { toast, showLogin } from '../store.js'
import { esc } from '../utils.js'

const base = ref(''), model = ref(''), key = ref(''), pps = ref(10), interval = ref(600), box = ref('')
const adminBox = ref(''), apikeyBox = ref('')
const pwOld = ref(''), pwNew = ref('')

async function loadSettings() {
  const j = await api(ep.settings())
  base.value = j.openai_base_url||''
  model.value = j.openai_model||''
  pps.value = j.points_per_second??10
  interval.value = j.monitor_interval??600
  box.value = 'API Key 已配置：'+(j.openai_configured?'是':'否')+'（出于安全不回显明文）'
  adminBox.value = `当前管理员：<b>${esc(j.admin_user||'-')}</b>${j.admin_needs_change?' <span class="badge b-warn">建议修改默认密码</span>':''} · 对外 API Key：${esc(j.api_key_masked||'未设置')}`
}
async function saveSettings() {
  const body = { openai_base_url:base.value||null, openai_model:model.value||null, openai_api_key:key.value||null,
    points_per_second:+pps.value||null, monitor_interval:+interval.value||null }
  const j = await api(ep.settings(), { method:'POST', body:JSON.stringify(body) })
  box.value = '已保存。API Key 配置：'+(j.openai_configured?'是':'否')
  key.value = ''
  toast('设置已保存')
}
async function changePassword() {
  if (!pwOld.value||!pwNew.value) return toast('请填写新旧密码', false)
  await api(ep.adminPassword(), { method:'POST', body:JSON.stringify({ old_password:pwOld.value, new_password:pwNew.value }) })
  toast('密码已修改，请重新登录'); clearToken(); showLogin()
}
async function showApiKey() {
  const j = await api(ep.adminApikey())
  apikeyBox.value = `<p class="small">对外 API Key（调用 /api/v1/* 时通过 <code>Authorization: Bearer</code> / <code>X-Api-Key</code> / <code>?api_key=</code> 携带）：</p><pre>${esc(j.api_key)}</pre>`
}
async function regenApiKey() {
  const j = await api(ep.settings(), { method:'POST', body:JSON.stringify({ regenerate_api_key:true }) })
  apikeyBox.value = `<p class="small">已重置，新 Key：</p><pre>${esc(j.api_key)}</pre>`
  toast('API Key 已重置')
}
onMounted(loadSettings)
</script>
