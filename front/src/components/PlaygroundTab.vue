<template>
  <div class="card">
    <h2>在线 Playground（图片 / 视频 / 音频统一试用）</h2>
    <div class="toptab">
      <button v-for="k in ['video','image','audio']" :key="k" :class="{active:pgType===k}" @click="setPg(k)">{{ {video:'视频',image:'图片',audio:'音频'}[k] }}</button>
    </div>
    <div class="row">
      <div style="flex:1;min-width:300px"><label>提示词 prompt</label><textarea v-model="prompt" rows="2" style="width:100%" placeholder="一只猫在星空下奔跑"></textarea></div>
    </div>
    <div class="row" style="margin-top:8px">
      <div><label>模型/工具(可选)</label><input v-model="model" placeholder="留空=自动选" style="width:200px"></div>
      <div><label>指定账号(可选)</label><input v-model="account" placeholder="留空=交叉选号" style="width:160px"></div>
      <div><label>选号策略</label><select v-model="strategy"><option value="balanced">均衡</option><option value="least_used">最少使用</option><option value="most_points">积分最多</option><option value="vip_preferred">VIP优先</option></select></div>
    </div>
    <div v-if="pgType==='video'" class="row" style="margin-top:8px">
      <div><label>时长(秒)</label><select v-model="dur"><option>5</option><option>10</option><option selected>15</option><option>30</option></select></div>
      <div><label>分辨率</label><select v-model="res"><option>480p</option><option selected>720p</option><option>1080p</option><option>2k</option><option>4k</option></select></div>
      <div><label>格式</label><select v-model="fmt"><option>mp4</option><option>webm</option><option>mov</option><option>gif</option></select></div>
      <div><label>帧率</label><select v-model="fps"><option>24</option><option>25</option><option selected>30</option></select></div>
      <div><label>比例</label><select v-model="ar"><option value="">默认</option><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>21:9</option></select></div>
    </div>
    <div v-if="pgType==='image'" class="row" style="margin-top:8px">
      <div><label>宽</label><input v-model.number="w" type="number" style="width:80px"></div>
      <div><label>高</label><input v-model.number="h" type="number" style="width:80px"></div>
      <div><label>格式</label><select v-model="ifmt"><option>png</option><option>jpg</option><option>webp</option></select></div>
    </div>
    <div v-if="pgType==='audio'" class="row" style="margin-top:8px">
      <div><label>时长(秒)</label><select v-model="adur"><option>5</option><option>10</option><option selected>15</option><option>30</option><option>60</option></select></div>
      <div><label>格式</label><select v-model="afmt"><option>mp4</option><option>wav</option><option>mp3</option></select></div>
    </div>
    <div class="row" style="margin-top:12px">
      <div><label>&nbsp;</label><label><input type="checkbox" v-model="dry"> 仅预览参数(dry_run)</label></div>
      <div><label>&nbsp;</label><button class="primary" @click="pgGen">生成</button></div>
      <div><label>&nbsp;</label><button class="ghost" @click="pgTools">探测可用工具</button></div>
    </div>
    <div class="small muted" style="margin-top:8px" v-html="toolsBox"></div>
    <div style="margin-top:12px" v-html="resultHtml"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api, ep } from '../api.js'
import { esc, safeUrl } from '../utils.js'

const pgType = ref('video')
const prompt = ref(''), model = ref(''), account = ref(''), strategy = ref('balanced'), dry = ref(false)
const dur = ref('15'), res = ref('720p'), fmt = ref('mp4'), fps = ref('30'), ar = ref('')
const w = ref(1024), h = ref(1024), ifmt = ref('png')
const adur = ref('15'), afmt = ref('mp4')
const toolsBox = ref(''), resultHtml = ref('')

function setPg(k) { pgType.value = k }
async function pgTools() {
  const j = await api(ep.tools(pgType.value))
  toolsBox.value = `推荐工具：<b>${esc(j.recommended_tool||'无')}</b> · 共 ${esc(j.count??0)} 个<br>` +
    (j.tools||[]).map(t=>'<span class="tag">'+esc(t.name||'-')+'</span>').join(' ')
}
async function pgGen() {
  const k = pgType.value
  const body = { prompt:prompt.value, model:model.value||null, account:account.value||null, strategy:strategy.value, dry_run:dry.value }
  if (k==='video') { body.duration=+dur.value; body.resolution=res.value; body.format=fmt.value; body.fps=+fps.value; body.aspect_ratio=ar.value||null }
  if (k==='image') { body.width=+w.value; body.height=+h.value; body.format=ifmt.value }
  if (k==='audio') { body.duration=+adur.value; body.format=afmt.value }
  const j = await api(ep.generate(k), { method:'POST', body:JSON.stringify(body) })
  resultHtml.value = renderGen(j)
}
function kindOf(res) {
  if (res.media_type) return res.media_type
  const f=(res.format||'').toLowerCase()
  if (['wav','mp3','m4a'].includes(f)) return 'audio'
  if (['png','jpg','jpeg','webp'].includes(f)) return 'image'
  return 'video'
}
function renderMedia(url, kind) {
  const src = safeUrl(url)
  if (!src) return '<div class="media-card"><div class="small muted">结果地址不可用</div></div>'
  const s = esc(src)
  const tag = kind==='image' ? `<img src="${s}">` : kind==='audio' ? `<audio src="${s}" controls></audio>` : `<video src="${s}" controls></video>`
  return `<div class="media-card">${tag}<div class="small muted">${esc(kind)}</div></div>`
}
function renderGen(j) {
  let head = `<div class="kpi"><div><b>${esc(j.account||'-')}</b><span>选用账号</span></div>` +
    (j.selection_reason?`<div><b>${esc(String(j.selection_reason||'').slice(0,30))}</b><span>选号原因</span></div>`:'') +
    (j.tool?`<div><b>${esc(j.tool)}</b><span>工具</span></div>`:'') + `</div>`
  let media = ''
  const res = j.result
  if (res && res.url) media = renderMedia(res.url, kindOf(res))
  return head + (media?'<div class="media-grid">'+media+'</div>':'') + `<pre>${esc(JSON.stringify(j,null,2))}</pre>`
}
</script>
