<template>
  <div class="card">
    <h2>账号活性监控（每 10 分钟巡检 + 自动领取权益）</h2>
    <div class="row">
      <button class="primary" @click="monitorCheck">立即巡检一次</button>
      <button class="ghost" @click="monitorStatus">查看监控状态</button>
    </div>
    <div style="margin-top:12px" v-html="box"></div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api, ep } from '../api.js'
import { esc, fmtTime } from '../utils.js'
import { toast } from '../store.js'

const box = ref('')
async function monitorStatus() {
  const j = await api(ep.monitorStatus()), rs = j.results||[]
  box.value = `<p class="small muted">运行中：${esc(j.running)} · 间隔：${esc(j.interval)}s · 上次巡检：${fmtTime(j.last_run_at)}</p>` +
    (rs.length ? `<table><thead><tr><th>账号</th><th>在线</th><th>类型</th><th>积分</th><th>免费算力</th><th>权益</th><th>错误</th></tr></thead><tbody>` +
      rs.map(r=>`<tr><td>${esc(r.account)}</td><td>${r.ok?'是':'否'}</td><td>${esc(r.account_type||'-')}</td><td>${esc(r.points??'-')}</td><td>${esc(r.free_power??'-')}</td><td>${r.checked_in?'是':'否'}</td><td>${esc(r.error||'-')}</td></tr>`).join('') + '</tbody></table>'
      : '<p class="muted">暂无巡检记录。</p>')
}
async function monitorCheck() { await api(ep.monitorCheck(), { method:'POST' }); monitorStatus(); toast('巡检完成') }
onMounted(monitorStatus)
</script>
