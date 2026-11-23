<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { buildReportHtml } from '../../reports/template.js'
import { deferRender } from '../../utils/rendering.js'
import ExportMenu from '../ExportMenu.vue'

const props = defineProps({ report: { type: Object, required: true }, initialState: { type: Object, default: () => ({}) }, readOnly: { type: Boolean, default: false }, storageKey: { type: String, default: '' }, exportSource: { type: Object, default: null } })
const emit = defineEmits(['ask', 'state', 'pin'])
const frame = ref(null)
const height = ref(1300)
const channel = `report-${Date.now()}-${Math.random().toString(36).slice(2)}`
const stateKey = () => props.storageKey || `gilead.bi.report.${props.report.id}.${props.report.revision}`
function restoredState() {
  if (Object.keys(props.initialState).length) return { ...props.initialState }
  try { return JSON.parse(localStorage.getItem(stateKey())) || {} } catch { return {} }
}
let currentState = restoredState()
const exportState = ref(currentState)
const hydration = ref(restoredState())
const srcdoc = ref('')
const rendering = ref(true)
const renderError = ref('')
let cancelRender = () => {}

function renderReport() {
  cancelRender()
  rendering.value = true
  renderError.value = ''
  cancelRender = deferRender(() => {
    try {
      srcdoc.value = buildReportHtml({ ...props.report, read_only: props.readOnly || props.report.read_only }, { state: hydration.value, bridge: channel })
    } catch {
      rendering.value = false
      renderError.value = '报告渲染失败，请重新渲染。'
    }
  })
}

function download(state = currentState) {
  const html = buildReportHtml(props.report, { state })
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${props.report.title.replace(/[\\/:*?"<>|]/g, '_')}_v${props.report.revision}.html`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function onMessage(event) {
  if (event.source !== frame.value?.contentWindow || event.data?.channel !== channel || event.data?.reportId !== props.report.id) return
  const data = event.data
  if (data.type === 'bi-report:resize') {
    height.value = Math.min(20000, Math.max(500, Number(data.height) || 1300))
    rendering.value = false
  }
  if (data.type === 'bi-report:state') {
    currentState = data.state || {}
    exportState.value = currentState
    try { localStorage.setItem(stateKey(), JSON.stringify(currentState)) } catch { /* private mode */ }
    emit('state', currentState)
  }
  if (data.type === 'bi-report:ask' && !props.readOnly && typeof data.text === 'string') emit('ask', data.text, { ...currentState, ...data.state, report_id: props.report.id, revision: props.report.revision, intent: 'revise_report' })
  if (data.type === 'bi-report:pin' && !props.readOnly && ['report','trend','contribution','kpis'].includes(data.section)) emit('pin', data.section, { ...currentState, ...data.state })
  if (data.type === 'bi-report:download') download(data.state)
  if (data.type === 'bi-report:print') {
    // A standalone tab can use its own print dialog while keeping the report sandboxed.
    const blob = new Blob([buildReportHtml(props.report, { state: currentState })], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
}
watch(() => [props.report, props.readOnly], () => {
  hydration.value = restoredState()
  currentState = restoredState()
  exportState.value = currentState
  renderReport()
}, { immediate: true })
onMounted(() => { window.addEventListener('message', onMessage); emit('state', currentState) })
onBeforeUnmount(() => { cancelRender(); window.removeEventListener('message', onMessage) })
defineExpose({ download })
</script>

<template>
  <div class="report-frame-wrap">
    <div v-if="exportSource" class="report-export-toolbar"><ExportMenu :source="exportSource.kind === 'report' ? { ...exportSource, state: exportState } : exportSource" :view="{ report_state: exportState }" label="导出报告" /></div>
    <div v-if="rendering || renderError" class="report-rendering" role="status"><p>{{ renderError || 'HTML 报告正在渲染…' }}</p><span v-if="!renderError">图表和数据表正在准备，可以继续浏览对话。</span><button v-else type="button" @click="renderReport">重新渲染</button></div>
    <iframe ref="frame" :srcdoc="srcdoc" :title="report.title" :data-report-id="report.id" :data-report-revision="report.revision" :style="{ height: `${height}px` }" sandbox="allow-scripts allow-downloads allow-modals" class="report-frame" :class="{ loading: rendering || renderError }" />
  </div>
</template>

<style scoped>
.report-frame-wrap { position:relative; border: 1px solid var(--line); border-radius: 22px; overflow: hidden; background: #f7f7f9; margin: 18px 0; width: 100%; }
.report-export-toolbar { display:flex; justify-content:flex-end; padding:12px 18px; border-bottom:1px solid var(--line); background:var(--paper); }
.report-frame { border: 0; display: block; width: 100%; }
.report-frame.loading { position:absolute; top:0; left:0; visibility:hidden; }
.report-rendering { min-height:600px; padding:30px; box-sizing:border-box; color:var(--ink-2); }
.report-rendering p { margin:0 0 12px; font-size:14px; }
.report-rendering span { font-size:12px; }
.report-rendering button { border:1px solid var(--line); border-radius:8px; padding:8px 13px; background:var(--paper); color:var(--accent); cursor:pointer; }
</style>
