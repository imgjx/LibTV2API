<template>
  <div class="card">
    <h2>团队与成员（统一纳管）</h2>
    <p class="small muted">liblib 平台原生没有团队功能：成员账号彼此独立、额度互不相通。这里把成员账号统一纳管，并可为每位成员设置每日额度上限；额度用尽的账号会被选号引擎自动跳过。</p>
    <div class="row">
      <div><label>团队名称</label><input v-model="tmName" placeholder="如：视频组" style="width:180px"></div>
      <div><label>备注</label><input v-model="tmNote" placeholder="如：负责视频产出的小组" style="width:240px"></div>
      <div><label>&nbsp;</label><button class="primary" @click="createTeam">新建团队</button></div>
    </div>
  </div>
  <div>
    <p v-if="!teams.length" class="muted">还没有团队。先在上面新建一个团队，再往里加成员。</p>
    <div v-for="t in teams" :key="t.id" class="team-card">
      <h3>{{ t.name }}<span class="small muted"> {{ t.member_count??0 }} 名成员 · {{ t.account_count??0 }} 个账号</span>
        <button class="danger" style="margin-left:auto" @click="delTeam(t.id)">删除团队</button></h3>
      <p v-if="t.note" class="small muted">{{ t.note }}</p>
      <div class="row" style="margin:8px 0">
        <div><label>成员姓名</label><input v-model="memName[t.id]" placeholder="如：张三" style="width:130px"></div>
        <div><label>每日额度(算力点,空=不限)</label><input v-model="memQuota[t.id]" type="number" placeholder="不限" style="width:130px"></div>
        <div><label>备注</label><input v-model="memNote[t.id]" placeholder="如：主力视频产出" style="width:170px"></div>
        <div><label>&nbsp;</label><button class="primary" @click="addMember(t.id)">新增成员</button></div>
      </div>
      <p v-if="!t.members||!t.members.length" class="small muted">该团队暂无成员。</p>
      <div v-for="m in (t.members||[])" :key="m.id" class="member-row">
        <span class="nm">{{ m.name }}</span>
        <span class="small muted">{{ m.note||'' }}</span>
        <span class="small">账号：{{ (m.account_ids||[]).join('、')||'未绑定账号' }}</span>
        <span class="quota-bar"><i :class="quotaCls(m)" :style="{width: quotaPct(m)+'%'}"></i></span>
        <span class="small">{{ m.quota_unlimited?'不限额':`${m.quota_used??0} / ${m.quota_limit} 点` }}</span>
        <button class="danger" @click="editQuota(m)">额度</button>
        <button class="danger" @click="delMember(m.id)">移除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api, ep } from '../api.js'
import { toast } from '../store.js'

const teams = ref([])
const tmName = ref(''), tmNote = ref('')
const memName = reactive({}), memQuota = reactive({}), memNote = reactive({})

function quotaPct(m) { return m.quota_unlimited?0:Math.min(100,Math.round((m.quota_used||0)/(m.quota_limit||1)*100)) }
function quotaCls(m) { const p=quotaPct(m); return p>=100?'bad':p>=80?'warn':'' }

async function loadTeams() { try { const j = await api(ep.teams()); teams.value = j.teams||[] } catch(e){} }
async function createTeam() {
  const name = tmName.value.trim()
  if (!name) return toast('请填团队名称', false)
  await api(ep.teams(), { method:'POST', body:JSON.stringify({ name, note:tmNote.value||'' }) })
  tmName.value=''; tmNote.value=''; toast('团队已创建'); loadTeams()
}
async function delTeam(id) {
  if (!window.confirm('删除该团队？其成员将被移除，账号保留。')) return
  await api(ep.teamDelete(id), { method:'DELETE' }); toast('团队已删除'); loadTeams()
}
async function addMember(teamId) {
  const name = (memName[teamId]||'').trim()
  if (!name) return toast('请填成员姓名', false)
  const q = memQuota[teamId]
  const body = { name, note:memNote[teamId]||'', quota_limit:(q===''||q==null||q==undefined)?null:Number(q) }
  await api(ep.teamMembers(teamId), { method:'POST', body:JSON.stringify(body) })
  memName[teamId]=''; memQuota[teamId]=''; memNote[teamId]=''
  toast('成员已添加'); loadTeams()
}
async function editQuota(m) {
  const v = window.prompt('设置每日额度上限（算力点）。留空表示不限额。\n当前已用：'+(m.quota_used||0), m.quota_limit==null?'':String(m.quota_limit))
  if (v===null) return
  const limitVal = (v.trim()==='')?null:Number(v.trim())
  await api(ep.memberQuota(m.id), { method:'POST', body:JSON.stringify({ quota_limit:limitVal }) })
  toast('额度已更新'); loadTeams()
}
async function delMember(id) {
  if (!window.confirm('移除该成员？其账号会保留但解除归属。')) return
  await api(ep.memberDelete(id), { method:'DELETE' }); toast('成员已移除'); loadTeams()
}
onMounted(loadTeams)
</script>
