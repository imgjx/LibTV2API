<template>
  <div class="card">
    <h2>通知通道</h2>
    <p class="small muted">团队运营需要主动找人：会员到期、登录态过期、额度超限与每日权益领取结果，都可以通过这里推送出去。</p>
    <div class="row" style="margin-top:10px">
      <span v-for="c in channels" :key="c.name" class="badge" :class="c.enabled?'b-alive':'b-free'">{{ c.label||c.name }}：{{ c.enabled?'已启用':'未启用' }}<template v-if="c.enabled&&!c.configured">（未配置）</template></span>
    </div>
    <div class="row" style="margin-top:10px">
      <button class="primary" @click="testNotify">发送测试通知</button>
      <button class="ghost" @click="scanAlerts">立即扫描告警</button>
    </div>
    <div class="small muted" style="margin-top:10px">{{ result }}</div>
  </div>

  <div class="card">
    <h2>邮件通道（SMTP）</h2>
    <div class="row" style="margin-top:10px">
      <div><label>启用</label><input type="checkbox" v-model="email.enabled"></div>
      <div style="flex:1;min-width:160px"><label>SMTP 主机</label><input v-model="email.smtp_host" style="width:100%" placeholder="smtp.exmail.qq.com"></div>
      <div><label>端口</label><input v-model.number="email.smtp_port" type="number" style="width:90px"></div>
      <div><label>SSL</label><input type="checkbox" v-model="email.use_ssl"></div>
      <div><label>STARTTLS</label><input type="checkbox" v-model="email.starttls"></div>
      <div><label>需认证</label><input type="checkbox" v-model="email.require_login"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div style="flex:1;min-width:200px"><label>账号</label><input v-model="email.smtp_user" style="width:100%"></div>
      <div style="flex:1;min-width:200px"><label>密码 / 授权码</label><input v-model="email.smtp_password" type="password" style="width:100%"></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div style="flex:1;min-width:200px"><label>发件人</label><input v-model="email.sender" style="width:100%"></div>
      <div style="flex:1;min-width:200px"><label>收件人（逗号分隔）</label><input v-model="emailTo" style="width:100%"></div>
      <div><label>&nbsp;</label><button class="primary" @click="saveNotify">保存通知配置</button></div>
    </div>
  </div>

  <div class="card">
    <h2>企业微信机器人</h2>
    <div class="row" style="margin-top:10px">
      <div><label>启用</label><input type="checkbox" v-model="wecom.enabled"></div>
      <div style="flex:1;min-width:300px"><label>Webhook 地址</label><input v-model="wecom.webhook_url" style="width:100%" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div style="flex:1;min-width:300px"><label>@提醒成员（逗号分隔，仅企业微信生效）</label><input v-model="wecomMentioned" style="width:100%"></div>
    </div>
  </div>

  <div class="card">
    <h2>告警规则</h2>
    <table style="margin-top:10px">
      <thead><tr><th>告警项</th><th>启用</th><th>阈值</th></tr></thead>
      <tbody>
        <tr v-for="r in ruleRows" :key="r.key">
          <td>{{ r.label }}</td>
          <td><input type="checkbox" v-model="r.enabled"></td>
          <td>
            <template v-if="r.key==='member_expiring'"><input v-model.number="r.days" type="number" style="width:80px"> 天</template>
            <template v-else-if="r.key==='token_expiring'"><input v-model.number="r.hours" type="number" style="width:80px"> 小时</template>
            <template v-else-if="r.key==='points_low'"><input v-model.number="r.threshold" type="number" style="width:90px"> 点</template>
            <template v-else-if="r.key==='quota_near_limit'"><input v-model.number="r.percent" type="number" style="width:80px"> %</template>
            <template v-else>-</template>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="row" style="margin-top:8px"><button class="primary" @click="saveRules">保存规则</button></div>
  </div>

  <div class="card">
    <h2>发送记录</h2>
    <div style="margin-top:10px">
      <p v-if="!history.length" class="muted">暂无发送记录。</p>
      <table v-else>
        <thead><tr><th>时间</th><th>通道</th><th>事件</th><th>结果</th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in history" :key="i">
            <td>{{ fmtTime(r.at) }}</td><td>{{ r.channel||'-' }}</td><td>{{ r.event_label||r.event||'-' }}</td>
            <td><span v-if="r.ok" class="badge b-alive">成功</span><span v-else class="badge b-dead">失败</span> {{ r.error||'' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api, ep } from '../api.js'
import { toast } from '../store.js'
import { fmtTime } from '../utils.js'

const RULE_DEFS = [
  ['member_expiring','会员即将到期提醒'], ['member_expired','会员已到期'], ['account_invalid','登录态过期'],
  ['token_expiring','登录令牌即将过期'], ['points_low','算力点余额偏低'], ['quota_near_limit','成员额度接近上限'],
  ['quota_exhausted','成员额度已用尽'], ['claim_failed','权益领取失败'], ['daily_digest','每日权益领取摘要'],
]
const channels = ref([]), history = ref([]), result = ref('')
const emailTo = ref(''), wecomMentioned = ref('')
const email = reactive({ enabled:false, smtp_host:'', smtp_port:465, use_ssl:true, starttls:true, require_login:true, smtp_user:'', smtp_password:'', sender:'' })
const wecom = reactive({ enabled:false, webhook_url:'' })
const ruleRows = ref([])

async function loadNotify() {
  const j = await api(ep.notifyStatus())
  channels.value = j.channels||[]
  const cfg = j.config||{}, em = cfg.email||{}, wc = cfg.wecom||{}
  Object.assign(email, {
    enabled:!!em.enabled, smtp_host:em.smtp_host||'', smtp_port:em.smtp_port||465,
    use_ssl:em.use_ssl!==false, starttls:em.starttls!==false, require_login:em.require_login!==false,
    smtp_user:em.smtp_user||'', smtp_password:'', sender:em.sender||'',
  })
  emailTo.value = (em.receivers||[]).join(',')
  Object.assign(wecom, { enabled:!!wc.enabled, webhook_url:wc.webhook_url||'' })
  wecomMentioned.value = (wc.mentioned||[]).join(',')
  const rules = j.rules||{}
  ruleRows.value = RULE_DEFS.map(([key,label]) => {
    const r = rules[key]||{}
    return {
      key, label, enabled:!!r.enabled,
      days:r.days??30, hours:r.hours??24, threshold:r.threshold??100, percent:r.percent??90,
    }
  })
  history.value = j.history||[]
}
async function saveNotify() {
  const to = emailTo.value.split(/[,;，]/).map(s=>s.trim()).filter(Boolean)
  const men = wecomMentioned.value.split(/[,;，]/).map(s=>s.trim()).filter(Boolean)
  const body = {
    email: { enabled:email.enabled, smtp_host:email.smtp_host.trim(), smtp_port:+email.smtp_port||465,
      use_ssl:email.use_ssl, starttls:email.starttls, require_login:email.require_login,
      smtp_user:email.smtp_user.trim(), smtp_password:email.smtp_password||null,
      sender:email.sender.trim(), receivers:to },
    wecom: { enabled:wecom.enabled, webhook_url:wecom.webhook_url.trim(), mentioned:men },
  }
  const j = await api(ep.notifyConfig(), { method:'POST', body:JSON.stringify(body) })
  toast(j.ok?'通知配置已保存':'保存失败'); loadNotify()
}
async function saveRules() {
  for (const r of ruleRows.value) {
    const payload = { enabled:r.enabled }
    if (r.key==='member_expiring') payload.days=+r.days||30
    else if (r.key==='token_expiring') payload.hours=+r.hours||24
    else if (r.key==='points_low') payload.threshold=+r.threshold||100
    else if (r.key==='quota_near_limit') payload.percent=+r.percent||90
    await api(ep.notifyRule(r.key), { method:'POST', body:JSON.stringify(payload) })
  }
  toast('告警规则已保存'); loadNotify()
}
async function testNotify() {
  const j = await api(ep.notifyTest(), { method:'POST', body:JSON.stringify({}) })
  const ok = (j.results||[]).filter(r=>r.ok).length
  result.value = '测试发送完成：成功 '+ok+' / '+(j.results||[]).length+' 个通道' +
    (j.results||[]).map(r=>'；'+r.channel+(r.ok?' 成功':' 失败：'+r.error)).join('')
  toast(ok?'测试通知已发送':'测试发送失败', ok>0)
}
async function scanAlerts() {
  const j = await api(ep.alertsScan(), { method:'POST', body:JSON.stringify({force:true}) })
  result.value = '扫描完成：命中 '+j.count+' 项（已按规则推送）'
  toast('告警扫描完成：'+j.count+' 项')
}
onMounted(loadNotify)
</script>
