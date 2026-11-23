<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/backend.js'
import { openSession, showToast, store } from '../store.js'
import { BOARD_ROLE_LABELS, BOARD_THEMES, boardLink, boardPath, canEditBoard, canManageBoard, filterBoards, scopeCaption } from '../workspace.js'
import { reportNumber } from '../reports/model.js'
import NavIcon from '../components/NavIcon.vue'
import AnswerCharts from '../components/chat/AnswerCharts.vue'
import ResultTable from '../components/chat/ResultTable.vue'
import ReportFrame from '../components/chat/ReportFrame.vue'
import ExportMenu from '../components/ExportMenu.vue'
import BoardEditorDialog from '../components/workspace/BoardEditorDialog.vue'
import BoardAccessDialog from '../components/workspace/BoardAccessDialog.vue'
import '../styles/workspace.css'

const route = useRoute(), router = useRouter()
const boards = ref([]), board = ref(null), loading = ref(true), error = ref(''), search = ref(''), tab = ref('all')
const editorOpen = ref(false), editingBoard = ref(null), accessOpen = ref(false), layoutEditing = ref(false), layout = ref([]), saving = ref(false), dragging = ref('')
const isDetail = computed(() => Boolean(route.params.id))
const visible = computed(() => filterBoards(boards.value, search.value, tab.value))
const myCount = computed(() => boards.value.filter(canManageBoard).length)
const shownItems = computed(() => layoutEditing.value ? layout.value : board.value?.items || [])
const editable = computed(() => canEditBoard(board.value))
const exportViews = ref({})
function exportSource(item = null) {
  return { kind: 'board', board_id: board.value.id, version: board.value.version,
    ...(item ? { item_id: item.id } : {}), views: exportViews.value }
}
function reportView(item, state) { exportViews.value[item.id] = { report_state: state } }
const manager = computed(() => canManageBoard(board.value))
const title = theme => BOARD_THEMES.find(item => item.id === theme)?.name || '业务专题'
const dateLabel = value => value ? new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : '—'
let loadSeq = 0
async function load() {
  const seq = ++loadSeq; loading.value = true; error.value = ''
  try {
    if (isDetail.value) { const result = await api.workspaceBoard(route.params.id); if (seq === loadSeq) board.value = result }
    else { const result = await api.workspaceBoards(); if (seq === loadSeq) boards.value = result.items }
  } catch (cause) { if (seq === loadSeq) { error.value = cause.message; board.value = null } }
  finally { if (seq === loadSeq) loading.value = false }
}
function edit(value = null) { editingBoard.value = value; editorOpen.value = true }
async function saved(value) {
  editorOpen.value = false
  if (isDetail.value) board.value = value
  else await router.push(boardPath(value.id))
  showToast('看板已保存')
}
function accessSaved(value) { board.value = value; accessOpen.value = false }
function startLayout() { layout.value = JSON.parse(JSON.stringify(board.value.items)); layoutEditing.value = true; error.value = '' }
function move(id, offset) {
  const index = layout.value.findIndex(item => item.id === id), target = index + offset
  if (target < 0 || target >= layout.value.length) return
  const [item] = layout.value.splice(index, 1); layout.value.splice(target, 0, item)
}
function drop(id) {
  const from = layout.value.findIndex(item => item.id === dragging.value), to = layout.value.findIndex(item => item.id === id)
  if (from < 0 || to < 0 || from === to) return
  const [item] = layout.value.splice(from, 1); layout.value.splice(to, 0, item); dragging.value = ''
}
async function saveLayout() {
  saving.value = true; error.value = ''
  try { board.value = await api.saveWorkspaceLayout(board.value.id, { version: board.value.version, items: layout.value.map(({ id, title, width }) => ({ id, title, width })) }); layoutEditing.value = false; showToast('看板布局已保存') }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function removeBoard() {
  if (!window.confirm(`删除「${board.value.name}」及其中保存的图表？原问答仍会保留。`)) return
  saving.value = true
  try { await api.deleteWorkspaceBoard(board.value.id); await router.push('/workspace'); showToast('看板已删除') }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function copyLink() { try { await navigator.clipboard.writeText(boardLink(board.value.id)); showToast('链接已复制，只有获授权的账号可访问') } catch { showToast('复制失败，请从浏览器地址栏复制此看板链接') } }
async function source(item) {
  try { await Promise.all([openSession(item.source.session_id), router.push('/')]) }
  catch (cause) { showToast(cause.message) }
}
onMounted(load)
</script>

<template>
  <main class="ws-page">
    <template v-if="!isDetail">
      <header class="ws-page-head"><div><div class="ws-eyebrow">YOUR BUSINESS, IN VIEW</div><h1>看板</h1><p>收藏对话中的图表和数据表，组织成主题看板，与团队共享业务发现。</p></div><button class="ws-button primary" @click="edit()"><NavIcon name="plus" />创建看板</button></header>
      <section class="ws-overview"><div><span>主题看板</span><b>{{ boards.length.toString().padStart(2,'0') }}</b></div><div><span>我创建的</span><b>{{ myCount.toString().padStart(2,'0') }}</b></div><div><span>共享给我</span><b>{{ (boards.length-myCount).toString().padStart(2,'0') }}</b></div><div class="ws-overview-note"><i>◈</i><p>重要的业务发现<br /><small>从个人分析，到团队共识</small></p></div></section>
      <div class="ws-list-toolbar"><div class="ws-tabs"><button v-for="item in [{id:'all',name:'全部看板'},{id:'mine',name:'我创建的'},{id:'shared',name:'共享给我'}]" :key="item.id" :class="{ on: tab===item.id }" @click="tab=item.id">{{ item.name }}</button></div><input v-model="search" class="ws-search" aria-label="搜索主题看板" placeholder="搜索看板名称或主题" /></div>
      <p v-if="loading" class="ws-empty">正在准备看板…</p>
      <div v-else-if="!error" class="ws-board-grid"><button v-for="item in visible" :key="item.id" class="ws-board-card" :class="item.theme" @click="router.push(boardPath(item.id))"><div class="ws-board-cover"><div class="ws-cover-grid"></div><span>{{ title(item.theme) }}</span><svg viewBox="0 0 300 76" fill="none" aria-hidden="true"><path d="M0 63 38 52 70 57 110 30 150 38 190 18 230 27 270 7 300 13" /><path d="M0 70 38 64 70 66 110 48 150 53 190 40 230 43 270 26 300 31" /></svg><div class="ws-cover-mini"><i></i><i></i><i></i><i></i></div></div><div class="ws-board-copy"><div class="ws-board-name"><h2>{{ item.name }}</h2><span>↗</span></div><p>{{ item.description || '汇集有数据依据的业务发现' }}</p><div class="ws-board-meta"><span>{{ item.card_count }} 项内容</span><span class="ws-role" :class="item.my_role">{{ BOARD_ROLE_LABELS[item.my_role] }}</span></div><footer><span>{{ item.owner_name }}<small v-if="item.member_count"> · {{ item.member_count }} 位成员</small></span><span>{{ dateLabel(item.updated_at) }} 更新</span></footer></div></button><button v-if="tab!=='shared' && !search" class="ws-create-card" @click="edit()"><span>＋</span><b>一个主题，一份看板</b><p>从问答图表、数据表或分析报告开始</p></button></div>
      <div v-if="!loading && !visible.length && !error && tab==='shared'" class="ws-empty-state"><NavIcon name="users" /><h2>团队的发现，也能汇聚到这里</h2><p>他人授权给你的看板会出现在这里。</p></div>
    </template>
    <template v-else>
      <header class="ws-detail-head"><div><router-link class="ws-back" to="/workspace">← 看板</router-link><div class="ws-detail-title"><h1>{{ board?.name || '主题看板' }}</h1><span v-if="board" class="ws-role" :class="board.my_role">{{ BOARD_ROLE_LABELS[board.my_role] }}</span></div><p>{{ board?.description || '将图表、数据表与指标汇集在同一份业务主题中' }}</p></div><div v-if="board" class="ws-detail-actions"><ExportMenu v-if="!layoutEditing" :source="exportSource()" label="导出看板" /><button class="ws-button" @click="copyLink">复制链接 ↗</button><button v-if="manager && !layoutEditing" class="ws-button" @click="accessOpen=true"><NavIcon name="users" />分享与权限<span v-if="board.member_count" class="ws-count">{{ board.member_count }}</span></button><button v-if="editable && !layoutEditing" class="ws-button primary" @click="startLayout">编辑看板</button><template v-if="layoutEditing"><button class="ws-button" :disabled="saving" @click="layoutEditing=false">取消</button><button class="ws-button primary" :disabled="saving" @click="saveLayout">{{ saving ? '保存中…' : '保存布局' }}</button></template></div></header>
      <div v-if="board" class="ws-detail-meta"><span class="ws-status-dot"></span><span>{{ title(board.theme) }}</span><span>{{ board.card_count }} 项内容</span><span>{{ board.owner_name }} 创建</span><span>更新于 {{ dateLabel(board.updated_at) }}</span><span class="ws-snapshot-note">数据快照 · 保留各图表的原统计范围</span><button v-if="editable && !layoutEditing" @click="edit(board)">编辑名称</button><button v-if="manager && !layoutEditing" class="ws-danger" :disabled="saving" @click="removeBoard">删除看板</button></div>
      <div v-if="layoutEditing" class="ws-layout-hint"><span>✦</span>拖动卡片调整顺序，也可以用上移 / 下移按钮。标题、宽度与移除操作将在保存后生效。</div>
      <p v-if="loading" class="ws-empty">正在加载看板…</p>
      <div v-if="board && shownItems.length" class="ws-tile-grid"><article v-for="(item,index) in shownItems" :key="item.id" class="ws-tile" :class="[item.width,item.kind,{ editing:layoutEditing, dragging:dragging===item.id }]" @dragover.prevent @drop.prevent="drop(item.id)"><div v-if="layoutEditing" class="ws-tile-tools"><button type="button" class="ws-drag-handle" draggable="true" aria-label="拖动内容排序" @dragstart="dragging=item.id; $event.dataTransfer.setData('text/plain',item.id)" @dragend="dragging=''">⠿</button><input v-model="item.title" maxlength="120" required aria-label="内容标题" /><select v-model="item.width" aria-label="内容宽度"><option value="half">半宽</option><option value="full">整行</option></select><button :disabled="index===0" :aria-label="`上移${item.title}`" @click="move(item.id,-1)">↑</button><button :disabled="index===shownItems.length-1" :aria-label="`下移${item.title}`" @click="move(item.id,1)">↓</button><button class="ws-danger" :aria-label="`移除${item.title}`" @click="layout=layout.filter(tile=>tile.id!==item.id)">移除</button></div><header class="ws-tile-head"><div><span class="ws-tile-kicker">{{ item.source.chatbot_name }}</span><h2>{{ item.title }}</h2></div><span class="ws-tile-kind">{{ item.kind==='analysis' ? '完整分析' : item.kind==='report' ? '交互报告' : item.kind==='kpi' ? '指标卡' : item.kind==='table' ? '数据表' : '业务图表' }}</span></header><p class="ws-tile-scope">{{ scopeCaption(item.source) }}<span v-if="item.source.sample"> · 样例数据</span></p><div v-if="item.kind==='kpi'" class="ws-kpi-grid"><div v-for="(metric,i) in item.snapshot.metrics" :key="i" :class="{ primary:i===0 }"><span>{{ metric.label }}</span><b :class="{ negative: Number(metric.value)<0 }">{{ metric.value == null ? '—' : reportNumber(metric.value, metric.unit==='%'?'percent':'compact') }}<small v-if="metric.value!=null && metric.unit!=='%'">{{ metric.unit }}</small></b><p>{{ metric.value == null ? '当前数据未提供可比基数' : '按收藏范围汇总' }}</p></div></div><ReportFrame v-else-if="item.kind==='report'" :report="item.snapshot" :read-only="true" :storage-key="`gilead.workspace.item.${item.id}`" @state="state => reportView(item, state)" /><ResultTable v-else-if="item.kind==='table'" :data="item.snapshot.data" title="数据表" :filename="item.title" :export-source="exportSource(item)" /><AnswerCharts v-else :charts="item.snapshot" :hide-title="true" :export-source="exportSource(item)" @view-change="value => exportViews[item.id] = value" /><footer class="ws-tile-footer"><ExportMenu :source="exportSource(item)" label="导出此项" /><span>保存于 {{ dateLabel(item.created_at) }}</span><button v-if="item.source.owner_id===store.user?.id && item.source.session_id && store.chatbotId===item.source.chatbot_id" @click="source(item)">查看原对话 ↗</button></footer></article></div>
      <div v-else-if="board && !loading" class="ws-empty-state"><NavIcon name="chat" /><h2>把图表和数据表汇集到这个主题</h2><p>在问答的图表或数据表中点击「加入看板」。</p><router-link class="ws-button primary" to="/">去业务对话 →</router-link></div>
    </template>
    <div v-if="error" class="ws-error" role="alert">{{ error }}<button class="ws-button" @click="layoutEditing=false;load()">刷新</button></div>
    <BoardEditorDialog v-if="editorOpen" :board="editingBoard" @close="editorOpen=false" @saved="saved" /><BoardAccessDialog v-if="accessOpen && board" :board="board" @close="accessOpen=false" @saved="accessSaved" />
  </main>
</template>
