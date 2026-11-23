<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { api } from '../../api/backend.js'
import { showToast, store } from '../../store.js'
import { decorateAnswerTables } from '../../utils/report.js'
import { renderMarkdown, sanitizeHtml } from '../../utils/markdown.js'
import { downloadRunExport, exportIdsFromHref } from '../../utils/xlsxDownload.js'
import AnswerCharts from './AnswerCharts.vue'
import ReportFrame from './ReportFrame.vue'
import DeferredContent from './DeferredContent.vue'
import ExportMenu from '../ExportMenu.vue'
const AnswerSkillDialog = defineAsyncComponent(() => import('./AnswerSkillDialog.vue'))
const PinToBoardDialog = defineAsyncComponent(() => import('../workspace/PinToBoardDialog.vue'))

const props = defineProps({ msg: { type: Object, required: true } })
const emit = defineEmits(['ask'])

// The reasoning path is reference material, not the answer: folded until
// the user asks for it.
const pathOpen = ref(false)
const feedbackRating = ref('')
const feedbackBusy = ref(false)
const feedbackLoaded = ref(false)
const skillOpen = ref(false)
const pinSource = ref(null)
const pinTitle = ref('')
const exportViews = ref({})
const answerExportSource = computed(() => ({
  kind: 'answer', run_id: props.msg.runId, report_state: props.msg.reportState || {}, views: exportViews.value,
}))
function chartExportSource(bundle) {
  return { kind: 'answer_analysis', run_id: props.msg.runId, chart_type: bundle.default_type,
    ...(bundle.event_cursor ? { chart_cursor: bundle.event_cursor } : {}) }
}
function rememberExportView(bundle, value) {
  if (bundle.event_cursor) exportViews.value[bundle.event_cursor] = value
}
const canSaveSkill = computed(() => store.user?.role === 'admin' && props.msg.runId && props.msg.status === 'completed' && Boolean(proseText.value))

const DONE_STATUSES = new Set([
  'completed', 'done', 'partial', 'failed', 'client_cancelled', 'cancelled',
])
const feedbackReady = computed(() => {
  if (!props.msg.runId) return false
  if (props.msg.status === 'waiting_clarification') return false
  if (props.msg.answer?.done) return true
  return DONE_STATUSES.has(props.msg.status)
})

const liveText = computed(() => props.msg.answer.md || props.msg.answer.draft)
const proseText = computed(() => liveText.value || '')
const canPin = computed(() => Boolean(props.msg.runId) && !store.busy && Boolean(props.msg.answer.md))
const html = computed(() => decorateAnswerTables(sanitizeHtml(renderMarkdown(proseText.value)), canPin.value))
const report = computed(() => props.msg.report || null)
const suggestions = computed(() => props.msg.suggestions?.questions || [])
const chartBundle = computed(() => props.msg.charts || null)
const chartCards = computed(() => props.msg.chartCards?.length ? props.msg.chartCards : chartBundle.value ? [chartBundle.value] : [])
const show = computed(() => Boolean(liveText.value || report.value || props.msg.reportLoading || props.msg.reportError || props.msg.failure || props.msg.charts?.charts?.length || suggestions.value.length || feedbackReady.value))
function reportState(state) { props.msg.reportState = state }
function reportAsk(text, context) { emit('ask', text, context) }
function pinChart(type, bundle) {
  pinSource.value = { kind: 'answer_chart', run_id: props.msg.runId, chart_type: type,
    ...(bundle.event_cursor ? { chart_cursor: bundle.event_cursor } : {}) }
  const chart = bundle.charts?.find(item => item.type === type)
  pinTitle.value = chart?.option?.title?.text || chart?.label || '业务图表'
}
function pinAnalysis(type, bundle) {
  pinSource.value = { kind: 'answer_analysis', run_id: props.msg.runId, chart_type: type,
    ...(bundle.event_cursor ? { chart_cursor: bundle.event_cursor } : {}) }
  pinTitle.value = bundle.title || '完整分析'
}
function pinChartTable(selection, bundle) {
  pinSource.value = { kind: 'chart_table', run_id: props.msg.runId,
    chart_type: selection.type, table_view: selection.view,
    ...(bundle.event_cursor ? { chart_cursor: bundle.event_cursor } : {}) }
  pinTitle.value = `${bundle.title || '业务分析'} · ${selection.view === 'details' ? '查询明细' : '图表数据'}`
}
function pinReport(section, state) {
  pinSource.value = { kind: 'report', run_id: props.msg.runId, report_id: report.value.id,
    report_revision: report.value.revision, section, state }
  pinTitle.value = `${report.value.title}${({ trend: ' · 趋势', contribution: ' · 贡献分析', kpis: ' · 核心指标' })[section] || ''}`
}

function askSuggestion(text) {
  const question = String(text || '').trim()
  if (question) emit('ask', question)
}

const path = computed(() => {
  const items = []
  for (const step of props.msg.steps || []) {
    for (const tool of step.tools || []) {
      if (tool.name === 'ask_user') continue
      items.push({
        index: items.length + 1,
        label: tool.label,
        summary: tool.summary,
        ok: tool.ok,
        done: tool.state === 'done',
      })
    }
  }
  return items
})

const usage = computed(() => props.msg.answer.usage || null)
const STATUS_LABEL = {
  completed: '完成',
  done: '完成',
  partial: '部分完成',
  running: '生成中',
  starting: '启动中',
  waiting_clarification: '待确认',
  failed: '失败',
  client_cancelled: '已停止',
  resuming: '继续分析',
}
const statusLabel = computed(() => STATUS_LABEL[props.msg.status] || props.msg.status)
const tokenLabel = computed(() => {
  const total = usage.value?.total_tokens
  if (total == null || total === '') return ''
  return `${Number(total).toLocaleString('zh-CN')} tokens`
})

async function onAnswerClick(event) {
  const button = event.target.closest('button[data-answer-table]')
  if (button && canPin.value) {
    const index = Number(button.dataset.answerTable)
    const nodes = [...event.currentTarget.querySelectorAll('h1,h2,h3,h4,table')]
    const table = event.currentTarget.querySelectorAll('table')[index]
    const heading = nodes.slice(0, nodes.indexOf(table)).reverse().find(node => node.tagName !== 'TABLE')
    pinSource.value = { kind: 'answer_table', run_id: props.msg.runId, table_index: index }
    pinTitle.value = heading?.textContent || `回答数据表 ${index + 1}`
    return
  }
  const anchor = event.target.closest('a')
  if (!anchor) return
  const ids = exportIdsFromHref(anchor.getAttribute('href'))
  if (!ids) return
  event.preventDefault()
  try {
    await downloadRunExport(ids.runId, ids.exportId)
  } catch (error) {
    showToast(error.message || '下载失败')
  }
}

async function loadFeedback() {
  if (!props.msg.runId || feedbackLoaded.value) return
  feedbackLoaded.value = true
  try {
    const row = await api.getFeedback(props.msg.runId)
    if (row?.rating) feedbackRating.value = row.rating
  } catch {
    /* ignore: first-time or offline */
  }
}

async function submitFeedback(rating) {
  if (!props.msg.runId || feedbackBusy.value) return
  if (feedbackRating.value === rating) return
  feedbackBusy.value = true
  try {
    const row = await api.submitFeedback({
      run_id: props.msg.runId,
      rating,
      question: props.msg.question || '',
      session_id: props.msg.sessionId || undefined,
    })
    feedbackRating.value = row.rating || rating
    showToast(rating === 'up' ? '已记录点赞' : '已记录点踩')
  } catch (error) {
    showToast('反馈提交失败：' + (error.message || '请稍后重试'))
  } finally {
    feedbackBusy.value = false
  }
}

watch(
  feedbackReady,
  (ready) => {
    if (ready) void loadFeedback()
  },
  { immediate: true },
)

watch(
  () => props.msg.runId,
  () => {
    feedbackLoaded.value = false
    feedbackRating.value = ''
    if (feedbackReady.value) void loadFeedback()
  },
)
</script>

<template>
  <section v-if="show" class="ans" aria-label="回答">
    <header class="answer-head">
      <div class="answer-meta">
        <span :class="['run-state', msg.status]">{{ statusLabel }}</span>
        <span v-if="tokenLabel" class="usage">{{ tokenLabel }}</span>
      </div>
      <button v-if="canSaveSkill" class="answer-skill-button" type="button" @click="skillOpen = true"><span aria-hidden="true">↗</span> 沉淀为技能</button>
      <ExportMenu v-if="msg.runId && msg.answer.done && msg.answer.md" :source="answerExportSource" label="导出本次回答" />
    </header>

    <div v-if="proseText" class="answer-body" v-html="html" @click="onAnswerClick"></div>
    <span v-if="msg.answer.streaming && !msg.answer.done" class="caret"></span>
    <p v-if="msg.reportLoading && !report" class="report-loading">正在加载交互报告…</p>
    <p v-if="msg.reportError" class="fail-note">{{ msg.reportError }}</p>
    <DeferredContent v-if="report" label="HTML 报告正在渲染…" :min-height="1300">
      <ReportFrame :report="report" :initial-state="msg.reportState || {}" :export-source="msg.runId ? { kind: 'report', run_id: msg.runId, report_id: report.id, report_revision: report.revision, section: 'report' } : null" @state="reportState" @ask="reportAsk" @pin="pinReport" />
    </DeferredContent>
    <template v-if="!report">
      <DeferredContent v-for="(bundle, index) in chartCards" :key="bundle.event_cursor || index" label="图表正在渲染…" :min-height="720">
        <AnswerCharts :charts="bundle" :allow-pin="Boolean(msg.runId) && !store.busy" :export-source="msg.runId && msg.answer.done ? chartExportSource(bundle) : null" @view-change="value => rememberExportView(bundle, value)" @pin="type => pinChart(type, bundle)" @pin-analysis="type => pinAnalysis(type, bundle)" @pin-table="selection => pinChartTable(selection, bundle)" />
      </DeferredContent>
    </template>
    <PinToBoardDialog v-if="pinSource" :source="pinSource" :title="pinTitle" @close="pinSource=null" />
    <div v-if="msg.failure" class="fail-note">执行失败：{{ msg.failure }}</div>
    <div v-if="path.length" class="path-list">
      <button class="path-head" type="button" @click="pathOpen = !pathOpen">
        <strong>推理路径</strong>
        <span class="path-meta">{{ path.length }} 次工具调用</span>
        <span class="path-chev">{{ pathOpen ? '收起 −' : '展开 +' }}</span>
      </button>
      <ol v-show="pathOpen">
        <li v-for="item in path" :key="item.index">
          <span class="path-state" :class="{ bad: item.done && item.ok === false }">{{ item.done ? (item.ok ? '✓' : '✕') : '…' }}</span>
          <span class="path-label">{{ item.label }}</span>
          <span class="path-summary">{{ item.summary }}</span>
        </li>
      </ol>
    </div>
    <div v-if="suggestions.length === 3" class="suggest-block" aria-label="推荐问题">
      <span class="suggest-title">或许你还想问</span>
      <div class="suggest-list">
        <button
          v-for="(text, index) in suggestions"
          :key="`${index}-${text}`"
          type="button"
          class="suggest-item"
          @click="askSuggestion(text)"
        >
          <span>{{ text }}</span>
          <i aria-hidden="true">↗</i>
        </button>
      </div>
    </div>


    <div v-if="feedbackReady" class="feedback-bar" aria-label="回答评价">
      <span class="feedback-label">这个回答有帮助吗？</span>
      <button
        type="button"
        class="feedback-btn"
        :class="{ on: feedbackRating === 'up' }"
        :disabled="feedbackBusy"
        title="点赞"
        aria-label="点赞"
        @click="submitFeedback('up')"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
          <path d="M7.5 21H5.2A1.2 1.2 0 0 1 4 19.8v-7.6A1.2 1.2 0 0 1 5.2 11h2.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
          <path d="M7.5 11.2 10.2 4.6A1.8 1.8 0 0 1 12 3.5h.3c1.1 0 1.9 1 1.7 2.1L13.4 9h4.8a2 2 0 0 1 1.9 2.5l-1.5 6.2A2.2 2.2 0 0 1 16.5 19.5H7.5V11.2Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <button
        type="button"
        class="feedback-btn"
        :class="{ on: feedbackRating === 'down', down: true }"
        :disabled="feedbackBusy"
        title="点踩"
        aria-label="点踩"
        @click="submitFeedback('down')"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
          <path d="M16.5 3H18.8A1.2 1.2 0 0 1 20 4.2v7.6A1.2 1.2 0 0 1 18.8 13h-2.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
          <path d="M16.5 12.8 13.8 19.4A1.8 1.8 0 0 1 12 20.5h-.3c-1.1 0-1.9-1-1.7-2.1L10.6 15H5.8a2 2 0 0 1-1.9-2.5l1.5-6.2A2.2 2.2 0 0 1 7.5 4.5H16.5v8.3Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <span v-if="feedbackRating" class="feedback-thanks">已记录，谢谢反馈</span>
    </div>
    <AnswerSkillDialog v-if="skillOpen" :run-id="msg.runId" @close="skillOpen = false" />
  </section>
</template>

<style scoped>
.answer-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.answer-skill-button { border: 1px solid var(--line-strong); border-radius: 20px; padding: 6px 12px; background: #ffffffbf; color: var(--ink-2); font: 500 12px var(--body-font); cursor: pointer; transition: color .2s, background .2s; }
.answer-skill-button:hover { color: var(--accent); background: var(--accent-soft); }
.answer-body :deep(.answer-table-actions) { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 14px; border-bottom:1px solid var(--line); background:var(--bg); color:var(--ink-2); font-size:11px; }
.answer-body :deep(.answer-table-actions button) { border:1px solid var(--line-strong); border-radius:7px; padding:5px 9px; background:var(--paper); color:var(--accent); font:inherit; cursor:pointer; white-space:nowrap; }
.suggest-block {
  align-items: flex-start;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 10px;
  margin-top: 12px;
  padding-top: 2px;
}
.suggest-title {
  color: var(--ink-3);
  flex: 0 0 auto;
  font: 500 12px/28px var(--body-font);
  margin: 0;
  white-space: nowrap;
}
.suggest-list {
  display: flex;
  flex: 1 1 220px;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.suggest-item {
  align-items: center;
  background: #fff;
  border: 1px solid var(--line-strong, rgba(20, 36, 30, .14));
  border-radius: 8px;
  color: var(--ink-2);
  cursor: pointer;
  display: inline-flex;
  font: 500 12px/1.3 var(--body-font);
  gap: 6px;
  max-width: 100%;
  padding: 5px 10px;
  text-align: left;
}
.suggest-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.suggest-item i {
  color: var(--ink-3);
  flex: 0 0 auto;
  font: 500 11px/1 var(--body-font);
  opacity: .75;
}
.suggest-item:hover {
  border-color: var(--accent, #1f6b52);
  color: var(--accent-dark, #144536);
}
.suggest-item:hover i { color: var(--accent, #1f6b52); opacity: 1; }
.path-list { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 10px; }
.path-head { align-items: baseline; background: transparent; border: 0; cursor: pointer; display: flex; gap: 10px; padding: 0; text-align: left; width: 100%; }
.path-head > strong { color: var(--ink-3); font: 650 11px var(--body-font); letter-spacing: .14em; }
.path-meta { color: var(--ink-3); flex: 1 1 auto; font: 500 12px var(--body-font); }
.path-chev { color: var(--ink-3); flex: 0 0 auto; font: 600 12px var(--body-font); }
.path-list ol { list-style: none; margin: 10px 0 0; padding: 0; }
.path-list li { align-items: baseline; display: flex; gap: 10px; padding: 7px 0; }
.path-list li::before { color: var(--ink-3); content: counter(list-item) "."; flex: 0 0 22px; font: 600 12px var(--mono-font); }
.path-state { color: var(--success); flex: 0 0 14px; font: 700 12px var(--mono-font); }
.path-state.bad { color: var(--danger); }
.path-label { color: var(--navy); flex: 0 0 auto; font: 650 10px/1.6 var(--mono-font); letter-spacing: .08em; }
.path-summary { color: var(--ink-2); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fail-note { background: #f8ece9; border-left: 3px solid var(--danger); color: var(--danger); font-size: 13px; margin-top: 16px; padding: 12px 14px; }
.feedback-bar {
  align-items: center;
  border-top: 1px solid var(--line);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
}
.feedback-label {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-right: 2px;
}
.feedback-btn {
  align-items: center;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--ink-2);
  cursor: pointer;
  display: inline-flex;
  height: 32px;
  justify-content: center;
  padding: 0;
  transition: border-color .15s, color .15s, background .15s;
  width: 32px;
}
.feedback-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.feedback-btn.on {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-dark);
}
.feedback-btn.on.down {
  background: #f8ece9;
  border-color: var(--danger);
  color: var(--danger);
}
.feedback-btn:disabled { opacity: .55; }
.feedback-thanks {
  color: var(--ink-3);
  font-size: 12px;
}
</style>
