<template>
  <div class="card">
    <h2>算力均摊（跨账号分段生成）</h2>
    <p class="small muted">仅当<strong>没有任何一个账号能独立生成完整时长</strong>时才会启用：把长视频按算力拆成多段（如 5+5+5 / 9+4+1+1 秒），每段交给算力点够用的账号接力生成，本地用 ffmpeg 拼接。若有账号能独立完成，将直接由该账号一次生成，不做分段。</p>
    <div class="row">
      <div style="flex:1;min-width:300px"><label>提示词 prompt</label><textarea v-model="prompt" rows="2" style="width:100%" placeholder="一只猫在星空下奔跑，镜头从特写拉到全景"></textarea></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>总时长(秒)</label><input v-model.number="dur" type="number" style="width:90px"></div>
      <div><label>模型(可选)</label><input v-model="model" placeholder="留空=自动" style="width:160px"></div>
      <div><label>分辨率</label><select v-model="res"><option>480p</option><option selected>720p</option><option>1080p</option><option>2k</option><option>4k</option></select></div>
      <div><label>格式</label><select v-model="fmt"><option>mp4</option><option>webm</option><option>mov</option><option>gif</option></select></div>
      <div><label>帧率</label><select v-model="fps"><option>24</option><option>25</option><option selected>30</option></select></div>
      <div><label>比例</label><select v-model="ar"><option value="">默认</option><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>21:9</option></select></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>每算力点消耗(可选)</label><input v-model.number="pps" type="number" style="width:90px"></div>
      <div><label>&nbsp;</label><label><input type="checkbox" v-model="dry"> 仅规划+分配(dry_run)</label></div>
      <div><label>&nbsp;</label><button class="primary" @click="balanceGen">算力均摊生成</button></div>
    </div>
    <div style="margin-top:12px" v-html="resultHtml"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api, ep } from '../api.js'
import { esc, safeUrl } from '../utils.js'

const prompt = ref(''), dur = ref(15), model = ref(''), res = ref('720p'), fmt = ref('mp4')
const fps = ref('30'), ar = ref(''), pps = ref(10), dry = ref(false)
const resultHtml = ref('')

function renderMedia(url) {
  const src = safeUrl(url)
  if (!src) return '<div class="small muted">结果地址不可用</div>'
  return `<video src="${esc(src)}" controls style="max-width:100%;border-radius:6px"></video>`
}
async function balanceGen() {
  const body = { prompt:prompt.value, duration:+dur.value, model:model.value||null, resolution:res.value,
    format:fmt.value, fps:+fps.value, aspect_ratio:ar.value||null, points_per_second:+pps.value||null, dry_run:dry.value }
  const j = await api(ep.videoBalance(), { method:'POST', body:JSON.stringify(body) })
  let h = ''
  h += j.strategy==='single'
    ? `<p class="small" style="color:var(--ok)">判定：<b>单账号即可完成</b>（${esc(j.single_account||'')}）—— ${esc(j.note||'')}</p>`
    : `<p class="small" style="color:var(--warn)">判定：<b>启用算力均摊</b> —— ${esc(j.note||'')}</p>`
  if (j.assign_error) h += `<p class="small" style="color:var(--bad)">分配提示：${esc(j.assign_error)}</p>`
  h += `<p class="small muted">分段来源：${j.openai_enabled?'智能分段规划':'确定性均分'} · 每算力点消耗 ${j.points_per_second} 点</p>`
  const plan = j.plan||{segments:[]}
  h += `<div class="kpi">` + (plan.segments||[]).map(s=>`<div><b>${esc(s.seconds??0)}s</b><span>${esc(s.account||'无账号')}</span></div>`).join('') + `</div>`
  let grid = ''
  for (const seg of (j.segments||[])) {
    const r = seg.result
    let card = `<div class="media-card"><div class="small">${seg.seconds}s · ${esc(seg.account||'-')} · ${esc(seg.tool||'')}</div>`
    if (r && r.url) card += renderMedia(r.url)
    else if (seg.error) card += `<div class="small" style="color:var(--bad)">${esc(seg.error)}</div>`
    else card += `<div class="small muted">${r?esc(JSON.stringify(r).slice(0,120)):'无结果'}</div>`
    card += '</div>'; grid += card
  }
  if (grid) h += `<div class="media-grid">${grid}</div>`
  if (j.ffmpeg_hint) h += `<p class="small muted">${esc(j.ffmpeg_hint)}</p>`
  h += `<pre>${esc(JSON.stringify(j,null,2))}</pre>`
  resultHtml.value = h
}
</script>
