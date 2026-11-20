<template>
  <div class="card">
    <h2>添加并登录账号（手机验证码 / 微信扫码 / Cookie）</h2>
    <p class="small muted">登录后自动识别账号类型（VIP / 免费）并纳入账号池，可再分配给团队成员统一管理；凭据仅存本机。也可在「账号池」页导入已有账号。</p>
    <div class="row">
      <div><label>手机号</label><input v-model="phone" placeholder="13800138000"></div>
      <div><label>代理(可选)</label><input v-model="proxy" placeholder="http://ip:port"></div>
      <div><label>备注</label><input v-model="note" placeholder="如：张三团队成员的账号"></div>
      <div><label>&nbsp;</label><button class="primary" @click="sendCode">发验证码</button></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>验证码</label><input v-model="code" placeholder="6位验证码"></div>
      <div><label>&nbsp;</label><button class="primary" @click="phoneLogin">登录并识别类型</button></div>
    </div>
    <hr style="border-color:var(--line);margin:16px 0">
    <button class="primary" @click="wechatAuth">微信扫码登录（二维码）</button>
    <div class="small muted" style="margin-top:8px" v-html="wxbox"></div>
  </div>

  <div class="card">
    <h2>Cookie 登录（从浏览器直接粘贴会话）</h2>
    <p class="small muted">适用于账号已在网页登录、想直接复用会话的场景：打开浏览器开发者工具（Network 或 Application 面板），复制该网站的 <b>Cookie</b> 字符串（形如 <code>a=1; b=2</code>，也支持 JSON 对象/数组），粘贴进来即可，无需验证码、无需扫码。凭据仅存本机。</p>
    <div class="row">
      <div style="flex:3"><label>Cookie</label><textarea v-model="cookies" rows="3" placeholder="a=1; b=2; usertoken=xxxx"></textarea></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>账号(可选)</label><input v-model="ckAccount" placeholder="已存在账号，用于刷新会话保留团队/备注"></div>
      <div><label>代理(可选)</label><input v-model="ckProxy" placeholder="http://ip:port"></div>
      <div><label>备注(可选)</label><input v-model="ckNote" placeholder="如：张三团队成员的账号"></div>
      <div><label>&nbsp;</label><button class="primary" @click="cookieLogin">用 Cookie 登录</button></div>
    </div>
    <p class="small muted">{{ ckTip }}</p>
  </div>

  <div class="card">
    <h2>合规声明与使用条例</h2>
    <p class="small muted">本工具面向团队自用，用于统一管理团队成员各自合法拥有的 liblib 账号。请遵守平台服务条款，不做逆向、破解、绕过平台限制、批量注册与账号买卖；凭据仅存本机，作者与维护者对不当使用或账号受限造成的后果不承担责任。完整条款见首次进入时的《使用条例与合规声明》，也可在「设置」中重新查看。</p>
    <div class="row" style="margin-top:8px"><button class="ghost" @click="showTerms">查看完整使用条例</button></div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { api, ep } from '../api.js'
import { toast } from '../store.js'
import { safeUrl, esc } from '../utils.js'

const showTerms = inject('showTerms', ()=>{})
const phone = ref(''), proxy = ref(''), note = ref(''), code = ref('')
const cookies = ref(''), ckAccount = ref(''), ckProxy = ref(''), ckNote = ref(''), ckTip = ref('')
const wxbox = ref('')
let wxTimer = null

onMounted(() => {
  // 账号池「重新登录」预填手机号
  if (window.__prefillPhone) { phone.value = window.__prefillPhone; window.__prefillPhone = '' }
})

async function sendCode() {
  if (!phone.value) return toast('请填手机号', false)
  await api(ep.phoneSendCode(), { method:'POST', body:JSON.stringify({ phone:phone.value, proxy:proxy.value||null }) })
  toast('验证码已下发')
}
async function phoneLogin() {
  const j = await api(ep.phoneLogin(), { method:'POST', body:JSON.stringify({ phone:phone.value, code:code.value, proxy:proxy.value||null, note:note.value }) })
  code.value = ''
  toast(j&&j.relogin?'重新登录成功，团队归属与备注已保留':'登录成功，已自动识别类型')
}
async function cookieLogin() {
  const c = cookies.value.trim()
  if (!c) { ckTip.value='请先粘贴 Cookie'; return }
  const body = { cookies:c, proxy:ckProxy.value||null, account:ckAccount.value.trim()||null, note:ckNote.value }
  ckTip.value='正在校验 Cookie 登录态…'
  try {
    const j = await api(ep.cookieLogin(), { method:'POST', body:JSON.stringify(body) })
    cookies.value=''; ckTip.value=''
    toast(j&&j.relogin?'Cookie 重新登录成功，团队归属与备注已保留':'Cookie 登录成功，已自动识别类型')
  } catch(e) { ckTip.value='Cookie 登录失败：'+((e&&e.message)||e) }
}
async function wechatAuth() {
  const j = await api(ep.wechatAuthorize())
  let qrHtml = ''
  try {
    const qr = await api(ep.wechatQr(j.state))
    const src = esc(safeUrl(qr.qr_png))
    qrHtml = src ? `<div class="qr"><img src="${src}" alt="微信扫码登录"></div>` : ''
  } catch(e) { qrHtml = '' }
  const link = esc(safeUrl(j.authorize_url))
  wxbox.value = `${qrHtml}<p class="small muted">使用微信扫一扫登录（已自动轮询）${link?`；也可 <a href="${link}" target="_blank" rel="noopener">点此打开授权链接</a>`:''}</p>`
  if (wxTimer) clearInterval(wxTimer)
  wxTimer = setInterval(()=>wechatPoll(j.state), 3000)
}
async function wechatPoll(state) {
  let j; try { j = await api(ep.wechatPoll(state)) } catch(e) { if(wxTimer){clearInterval(wxTimer);wxTimer=null;} return }
  if (j.status==='pending') return
  if (wxTimer) { clearInterval(wxTimer); wxTimer=null }
  if (j.status==='ok') { toast('微信登录成功'); return }
  toast('微信登录失败', false)
}
</script>
