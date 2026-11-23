<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, showToast, store } from '../store.js'
import { downloadRunExport, exportIdsFromHref } from '../utils/xlsxDownload.js'
import { renderMarkdown, sanitizeHtml } from '../utils/markdown.js'
import {
  STATUS_TEXT,
  buildSessionModel,
  roleLabels,
  filterItems,
  formatDuration,
  formatStamp,
  highlightJson,
  insertTurnHeaders,
  msBetween,
  oneLine,
  toolMeta,
} from '../utils/traceTimeline.js'

const STATUS_LABEL = {
  completed: '已完成',
  failed: '失败',
  running: '进行中',
  waiting_clarification: '待确认',
  cancelled: '已取消',
  partial: '部分完成',
}

/** Insight children store a long agent prefix on run.question; UI shows the short line. */
function displayRunQuestion(run) {
  if (!run) return ''
  const meta = run.insight_meta || {}
  const fromMeta = String(meta.display_question || '').trim()
  if (fromMeta) return fromMeta
  const raw = String(run.question || '').trim()
  if (!raw) return ''
  const marker = '【子问题】'
  if (raw.includes(marker)) {
    const tail = raw.split(marker).pop().trim()
    if (tail) return tail.slice(0, 300)
  }
  if (raw.includes('【执行纪律】') || raw.includes('【洞察技能')) {
    return `${raw.replace(/\s+/g, ' ').slice(0, 120)}…`
  }
  return raw
}
const GANTT_TRACKS = [
  { id: 'input', label: '输入' },
  { id: 'model', label: '模型' },
  { id: 'tools', label: '工具' },
]
const INSPECTOR_TABS = [
  { id: 'summary', label: '摘要' },
  { id: 'payload', label: '入参' },
  { id: 'result', label: '结果' },
  { id: 'schema', label: '说明' },
  { id: 'timing', label: '耗时' },
]
const characterName = computed(() => store.branding?.character_name || 'Gilead BI')
const KIND_HELP = computed(() => ({
  question: '用户在本轮提出的问题。',
  'clarify-answer': '用户对澄清问题的答复。',
  answer: `${characterName.value}基于本轮工具结果给出的回答。`,
  message: `${characterName.value}在调用工具前的思考与中间回应。`,
  call: '一次工具调用：左侧是入参，箭头后是返回摘要。',
  ledger: `进度台账快照：${characterName.value}对口径、术语、时间等要素的当前理解。`,
  clarify: `${characterName.value}认为口径有歧义，向用户发起澄清。`,
  memory: '本轮确认已写入个人记忆，后续提问会自动带上。',
  error: '运行或后台任务失败。',
}))
const labels = computed(() => roleLabels(characterName.value))

const runs = ref([])
const selectedRunId = ref('')
const trace = ref(null)
const loading = ref(true)
const detailLoading = ref(false)
const tab = ref('track')
const query = ref('')
const selectedId = ref('')
const inspectorTab = ref('summary')
let traceRequestSeq = 0

const session = computed(() => buildSessionModel(trace.value?.events || [], trace.value?.run || null, { assistantName: characterName.value }))
const children = computed(() => trace.value?.children || [])
const isInsightParent = computed(() => trace.value?.run?.mode === 'insight')
const parentRunId = computed(() => trace.value?.run?.parent_run_id || '')
const visibleItems = computed(() => filterItems(session.value.items, query.value))
const visibleRows = computed(() => insertTurnHeaders(visibleItems.value))
const selected = computed(() => session.value.items.find((item) => item.id === selectedId.value) || null)
const selectedMeta = computed(() => (selected.value?.role === 'tool' ? toolMeta(selected.value.name) : null))
const inspectorKicker = computed(() => {
  const item = selected.value
  if (!item) return ''
  const parts = []
  if (item.turn) parts.push(`第 ${item.turn} 回合`)
  if (item.step) parts.push(`第 ${item.step} 步`)
  return parts.join(' · ')
})
const inspectorOpen = computed(() => Boolean(selected.value) && tab.value === 'track')

async function reload() {
  loading.value = true
  try {
    runs.value = await api.runs({ limit: 50, offset: 0 })
    if (runs.value[0] && !selectedRunId.value) await selectRun(runs.value[0].id)
  } catch (error) {
    showToast('运行记录加载失败：' + error.message)
  } finally {
    loading.value = false
  }
}

async function selectRun(id) {
  const requestSeq = ++traceRequestSeq
  selectedRunId.value = id
  detailLoading.value = true
  trace.value = null
  selectedId.value = ''
  query.value = ''
  inspectorTab.value = 'summary'
  try {
    const result = await api.runTrace(id)
    if (requestSeq === traceRequestSeq) trace.value = result
  } catch (error) {
    if (requestSeq === traceRequestSeq) showToast('轨迹加载失败：' + error.message)
  } finally {
    if (requestSeq === traceRequestSeq) detailLoading.value = false
  }
}

function selectItem(item) {
  if (!item || item.rowKind === 'turn') return
  selectedId.value = item.id
  inspectorTab.value = 'summary'
  if (tab.value !== 'track') tab.value = 'track'
  nextTick(() => {
    document.getElementById(`log-${item.id}`)?.scrollIntoView({ block: 'nearest' })
  })
}

function selectById(id) {
  const item = session.value.items.find((entry) => entry.id === id)
  if (item) selectItem(item)
}

function closeInspector() {
  selectedId.value = ''
}

function asHtml(text) {
  return sanitizeHtml(renderMarkdown(text || ''))
}

function artifactSql(artifact) {
  const payload = artifact.payload || {}
  return payload.sql || payload.approved_sql || payload.query || ''
}

function copy(text) {
  const value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  navigator.clipboard?.writeText(value).then(() => showToast('已复制')).catch(() => showToast('复制失败'))
}

function exportLog() {
  if (!trace.value) return
  const payload = {
    run: trace.value.run,
    events: trace.value.events,
    timeline: session.value.items,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${characterName.value}轨迹-${trace.value.run.id.slice(0, 8)}.json`
  link.click()
  URL.revokeObjectURL(url)
  showToast('已导出日志')
}

function itemDuration(item) {
  if (!item) return '—'
  if (item.preview?.duration_ms != null) return formatDuration(item.preview.duration_ms)
  const ms = msBetween(item.startedAt, item.endedAt)
  if (ms == null) return '—'
  if (ms === 0) return '不到 1 秒'
  return formatDuration(ms)
}

async function downloadSelectedExport() {
  const ids = exportIdsFromHref(selected.value?.preview?.download_path)
  if (!ids) return
  try {
    await downloadRunExport(ids.runId, ids.exportId, selected.value.preview.filename)
  } catch (error) {
    showToast(error.message || '下载失败')
  }
}

function payloadOf(item) {
  if (!item) return null
  if (item.role === 'tool') return item.arguments ?? item.payload
  if (item.role === 'user') return item.content
  if (item.role === 'assistant') {
    return {
      content: item.content || '',
      reasoning: item.reasoning || '',
      finish_reason: item.finishReason || '',
      usage: item.usage || null,
      tool_calls: item.toolCalls || [],
    }
  }
  return item.payload
}

function resultOf(item) {
  if (!item) return null
  if (item.role === 'tool') return item.result || item.resultPayload || ''
  return item.result || item.content || item.payload
}

function pretty(value) {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

function onKey(event) {
  if (event.target.closest?.('input, textarea')) return
  if (event.key === 'Escape') {
    closeInspector()
    return
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  const ids = visibleItems.value.map((item) => item.id)
  if (!ids.length) return
  event.preventDefault()
  const delta = event.key === 'ArrowDown' ? 1 : -1
  const index = ids.indexOf(selectedId.value)
  const nextIndex = index === -1 ? 0 : Math.min(ids.length - 1, Math.max(0, index + delta))
  selectById(ids[nextIndex])
}

watch(selectedId, () => { inspectorTab.value = 'summary' })

onMounted(() => {
  reload()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="trace-page">
    <aside class="run-list">
      <header>
        <div class="eyebrow">轨迹</div>
        <h1>运行轨迹</h1>
        <button class="icon-action" title="刷新" @click="reload">↻</button>
      </header>
      <div v-if="loading" class="loading-state compact">加载中…</div>
      <button
        v-for="run in runs"
        :key="run.id"
        class="run-item"
        :class="{ on: selectedRunId === run.id }"
        @click="selectRun(run.id)"
      >
        <span :class="['run-dot', run.status]"></span>
        <div>
          <b>{{ displayRunQuestion(run) }}</b>
          <span>{{ formatDate(run.created_at) }} · {{ run.id.slice(0, 8) }}</span>
        </div>
        <small>{{ STATUS_LABEL[run.status] || run.status }}</small>
      </button>
      <div v-if="!loading && !runs.length" class="empty-state">
        <b>暂无运行</b>
        <span>完成一次问答后会出现在这里。</span>
      </div>
    </aside>

    <main class="trace-detail">
      <div v-if="detailLoading" class="loading-state">正在装载运行轨迹…</div>
      <div v-else-if="trace" class="session-panel">
        <header class="session-head">
          <div class="session-title">
            <h1 :title="trace.run.question">{{ displayRunQuestion(trace.run) }}</h1>
            <p>
              {{ formatDate(trace.run.created_at) }}
              · 会话 {{ trace.run.session_id?.slice(0, 10) || '—' }}
              · {{ STATUS_LABEL[trace.run.status] || trace.run.status }}
              <template v-if="isInsightParent"> · 数据洞察父任务</template>
              <template v-else-if="parentRunId"> · 洞察子任务</template>
            </p>
          </div>
          <div class="session-actions">
            <button
              v-if="parentRunId"
              class="export-btn"
              type="button"
              @click="selectRun(parentRunId)"
            >返回父任务</button>
            <span class="agent-chip">
              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <path d="M8 1.6l1.2 3.2 3.4.2-2.6 2.2.9 3.3L8 8.8 4.1 10.5l.9-3.3L2.4 5l3.4-.2L8 1.6z" fill="currentColor"/>
              </svg>
              {{ characterName }}
            </span>
            <button class="export-btn" type="button" @click="exportLog">
              导出日志
              <span aria-hidden="true">↓</span>
            </button>
          </div>
        </header>

        <section v-if="children.length" class="child-runs" aria-label="子任务">
          <h2>下钻子 Run</h2>
          <p>父任务编排的标准问数链路；点击进入完整子轨迹。</p>
          <div class="child-grid">
            <button
              v-for="child in children"
              :key="child.id"
              type="button"
              class="child-card"
              @click="selectRun(child.id)"
            >
              <span :class="['run-dot', child.status]"></span>
              <div>
                <b>{{ child.insight_meta?.angle || child.insight_meta?.kind || '子问题' }}</b>
                <span>{{ displayRunQuestion(child) }}</span>
              </div>
              <small>{{ STATUS_LABEL[child.status] || child.status }}</small>
            </button>
          </div>
        </section>

        <nav class="session-tabs" aria-label="轨迹视图">
          <button type="button" :class="{ on: tab === 'talk' }" @click="tab = 'talk'">对话</button>
          <button type="button" :class="{ on: tab === 'track' }" @click="tab = 'track'">轨迹</button>
          <button type="button" :class="{ on: tab === 'artifacts' }" @click="tab = 'artifacts'">产物</button>
        </nav>

        <div v-if="tab === 'track'" class="session-toolbar">
          <div class="meta-bits">
            <span><i class="meta-ico clock"></i>时长 <b>{{ formatDuration(session.durationMs) }}</b></span>
            <span><i class="meta-ico turns"></i>回合 <b>{{ session.turns }}</b></span>
            <span><i class="meta-ico calls"></i>调用 <b>{{ session.calls }}</b></span>
          </div>
          <label class="search">
            <span class="sr-only">搜索轨迹</span>
            <input v-model="query" type="search" placeholder="搜索" />
          </label>
        </div>

        <div v-if="tab === 'track'" class="gantt" aria-hidden="false">
          <div v-for="track in GANTT_TRACKS" :key="track.id" class="gantt-row">
            <span>{{ track.label }}</span>
            <div class="gantt-track">
              <button
                v-for="bar in session.gantt[track.id]"
                :key="bar.id"
                class="gantt-bar"
                type="button"
                :class="{ on: selectedId === bar.id }"
                :style="{ left: bar.left + '%', width: bar.width + '%', background: bar.color }"
                :title="bar.title"
                @click="selectById(bar.id)"
              />
            </div>
          </div>
        </div>

        <div class="session-shell" :class="{ 'has-inspector': inspectorOpen }">
          <section v-if="tab === 'talk'" class="session-main talk">
            <article
              v-for="item in session.conversation"
              :key="item.id"
              class="talk-card"
              :class="item.role"
            >
              <span class="role-pill" :class="item.role">{{ labels[item.role] }}</span>
              <div v-if="item.role === 'assistant'" class="talk-body md" v-html="asHtml(item.content)"></div>
              <p v-else class="talk-body">{{ item.content }}</p>
            </article>
            <div v-if="!session.conversation.length" class="empty-state">
              <b>还没有可展示的对话</b>
              <span>本轮可能停在澄清或尚未生成回答。</span>
            </div>
          </section>

          <section v-else-if="tab === 'track'" class="session-main log">
            <template v-for="row in visibleRows" :key="row.id">
              <div v-if="row.rowKind === 'turn'" class="turn-mark">回合 {{ row.turn }}</div>
              <button
                v-else
                :id="`log-${row.id}`"
                class="log-row"
                type="button"
                :class="[row.role, { on: selectedId === row.id, bad: row.ok === false }]"
                @click="selectItem(row)"
              >
                <span class="role-pill" :class="row.role">{{ labels[row.role] }}</span>
                <span class="log-line">
                  <b class="log-head">{{ row.headline }}</b>
                  <em v-if="row.detail" class="log-detail">{{ row.detail }}</em>
                  <template v-if="row.resultPreview">
                    <span class="log-arrow">→</span>
                    <span class="log-result">{{ row.resultPreview }}</span>
                  </template>
                </span>
              </button>
            </template>
            <div v-if="!visibleRows.length" class="empty-state">
              <b>{{ query ? '没有匹配的记录' : '没有事件' }}</b>
              <span>{{ query ? '换个关键词试试。' : '该运行尚未产生轨迹事件。' }}</span>
            </div>
          </section>

          <section v-else class="session-main artifacts">
            <div v-if="!trace.artifacts.length" class="empty-state">
              <b>没有持久化产物</b>
              <span>该运行可能在澄清阶段结束。</span>
            </div>
            <article v-for="artifact in trace.artifacts" :key="artifact.id" class="artifact-card">
              <header>
                <div>
                  <span class="artifact-kind">{{ artifact.kind }}</span>
                  <b>{{ artifact.atom_id || '运行级' }}</b>
                </div>
                <span>修订 {{ artifact.revision }} · {{ formatDate(artifact.created_at) }}</span>
              </header>
              <div v-if="artifactSql(artifact)" class="sql-block">
                <button type="button" @click="copy(artifactSql(artifact))">复制</button>
                <pre><code>{{ artifactSql(artifact) }}</code></pre>
              </div>
              <details>
                <summary>完整安全摘要</summary>
                <pre>{{ JSON.stringify(artifact.payload, null, 2) }}</pre>
              </details>
            </article>
          </section>

          <aside v-if="inspectorOpen" class="inspector" aria-label="事件详情">
            <header class="inspector-head">
              <span class="role-pill" :class="selected.role">{{ labels[selected.role] }}</span>
              <strong>{{ inspectorKicker || selected.title }}</strong>
              <button class="inspector-close" type="button" title="关闭" @click="closeInspector">×</button>
            </header>
            <nav class="inspector-tabs">
              <button
                v-for="entry in INSPECTOR_TABS"
                :key="entry.id"
                type="button"
                :class="{ on: inspectorTab === entry.id }"
                @click="inspectorTab = entry.id"
              >{{ entry.label }}</button>
            </nav>

            <div v-if="inspectorTab === 'summary'" class="inspector-body">
              <div class="kv">
                <span>层级</span>
                <div>{{ selected.hierarchy || '—' }} <em v-if="selected.role === 'tool'">›</em></div>
              </div>
              <div class="kv">
                <span>状态</span>
                <div :class="['status-text', selected.status]">{{ STATUS_TEXT[selected.status] || selected.status }}</div>
              </div>
              <div v-if="selected.role === 'tool' || selected.arguments" class="kv stack">
                <span>入参</span>
                <pre class="json" v-html="highlightJson(payloadOf(selected)) || '—'"></pre>
              </div>
              <div v-else-if="selected.content" class="kv stack">
                <span>内容</span>
                <pre class="plain">{{ selected.content }}</pre>
              </div>
              <div v-if="selected.result || selected.reasoning" class="kv stack">
                <span>结果</span>
                <pre class="plain">{{ selected.resultPreview || oneLine(selected.result, 200) }}</pre>
              </div>
              <div v-if="selectedMeta" class="kv stack">
                <span>说明</span>
                <div>
                  <b class="schema-name">{{ selectedMeta.name }}</b>
                  <p class="schema-desc">{{ selectedMeta.description }}</p>
                </div>
              </div>
              <div class="kv stack">
                <span>耗时</span>
                <dl class="timing">
                  <div><dt>开始</dt><dd>{{ formatStamp(selected.startedAt) }}</dd></div>
                  <div><dt>耗时</dt><dd>{{ itemDuration(selected) }}</dd></div>
                  <div><dt>时间来源</dt><dd>会话时间戳</dd></div>
                </dl>
              </div>
            </div>

            <div v-else-if="inspectorTab === 'payload'" class="inspector-body">
              <div class="pane-tools"><button type="button" @click="copy(pretty(payloadOf(selected)))">复制</button></div>
              <pre class="json fill" v-html="highlightJson(payloadOf(selected)) || '没有入参'"></pre>
            </div>

            <div v-else-if="inspectorTab === 'result'" class="inspector-body">
              <div class="pane-tools"><button type="button" @click="copy(pretty(resultOf(selected)))">复制</button></div>
              <div v-if="selected.preview?.download_path" class="result-table-wrap">
                <p class="result-meta">完整结果共 {{ selected.preview.row_count ?? '—' }} 行</p>
                <button type="button" @click="downloadSelectedExport">下载 {{ selected.preview.filename || 'xlsx' }}</button>
              </div>
              <div v-if="selected.preview?.columns?.length" class="result-table-wrap">
                <p class="result-meta">共 {{ selected.preview.row_count ?? selected.preview.rows?.length ?? 0 }} 行</p>
                <table class="result-table">
                  <thead>
                    <tr>
                      <th v-for="(column, index) in selected.preview.columns" :key="index">
                        {{ typeof column === 'string' ? column : (column.name || column.key || '列') }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, index) in (selected.preview.rows || []).slice(0, 30)" :key="index">
                      <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <pre v-else class="plain fill">{{ pretty(resultOf(selected)) || '没有结果' }}</pre>
            </div>

            <div v-else-if="inspectorTab === 'schema'" class="inspector-body schema">
              <template v-if="selectedMeta">
                <h3>{{ selectedMeta.name }}</h3>
                <p>{{ selectedMeta.description }}</p>
                <h4>参数</h4>
                <ul>
                  <li v-for="(spec, name) in selectedMeta.parameters" :key="name">
                    <code>{{ name }}</code>
                    <i>{{ spec.type }}</i>
                    <span>{{ spec.description }}</span>
                  </li>
                </ul>
              </template>
              <p v-else>{{ KIND_HELP[selected.kind] || '此事件没有额外说明。' }}</p>
            </div>

            <div v-else class="inspector-body">
              <dl class="timing big">
                <div><dt>开始</dt><dd>{{ formatStamp(selected.startedAt) }}</dd></div>
                <div><dt>结束</dt><dd>{{ formatStamp(selected.endedAt) }}</dd></div>
                <div><dt>耗时</dt><dd>{{ itemDuration(selected) }}</dd></div>
                <div><dt>时间来源</dt><dd>会话时间戳</dd></div>
              </dl>
            </div>
          </aside>
        </div>
      </div>
      <div v-else class="empty-state">
        <b>选择一次运行</b>
        <span>查看对话、逐步轨迹和持久化产物。</span>
      </div>
    </main>
  </div>
</template>

<style scoped>
.session-panel {
  background: var(--paper);
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}
.session-head {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding: 18px 28px 6px;
}
.session-title { min-width: 0; }
.session-title h1 {
  font-family: var(--display-font);
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -.02em;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-title p { color: var(--ink-3); font-size: 12px; margin-top: 4px; }
.session-actions { align-items: center; display: flex; flex: 0 0 auto; gap: 10px; }
.agent-chip {
  align-items: center;
  color: var(--ink-2);
  display: inline-flex;
  font-size: 13px;
  font-weight: 600;
  gap: 5px;
}
.agent-chip svg { color: var(--accent); }
.export-btn {
  align-items: center;
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: var(--ink);
  display: inline-flex;
  font-size: 12.5px;
  font-weight: 600;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
}
.export-btn:hover { background: var(--bg); }

.session-tabs {
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 18px;
  padding: 0 28px;
}
.session-tabs button {
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--ink-3);
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: -1px;
  padding: 10px 0 8px;
}
.session-tabs button.on { border-bottom-color: #2f6feb; color: var(--ink); }

.session-toolbar {
  align-items: center;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding: 10px 28px 6px;
}
.meta-bits { align-items: center; color: var(--ink-3); display: flex; font-size: 12px; gap: 18px; }
.meta-bits b { color: var(--ink-2); font-weight: 650; margin-left: 4px; }
.meta-ico {
  background: currentColor;
  display: inline-block;
  height: 12px;
  margin-right: 6px;
  mask-position: center;
  mask-repeat: no-repeat;
  mask-size: contain;
  opacity: .7;
  vertical-align: -1px;
  width: 12px;
}
.meta-ico.clock { mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><circle cx='8' cy='8' r='6' fill='none' stroke='black' stroke-width='1.6'/><path d='M8 4.5V8l2.4 1.5' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='round'/></svg>"); }
.meta-ico.turns { mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect x='3' y='3' width='10' height='10' rx='1.5' fill='none' stroke='black' stroke-width='1.6'/><path d='M5 6.5h6M5 9.5h4' stroke='black' stroke-width='1.6' stroke-linecap='round'/></svg>"); }
.meta-ico.calls { mask-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path d='M3 5h10M3 8h10M3 11h7' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='round'/></svg>"); }
.search { margin-left: auto; }
.search input {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 12.5px;
  height: 30px;
  padding: 0 12px 0 28px;
  width: 200px;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><circle cx='7' cy='7' r='4.2' fill='none' stroke='%23968990' stroke-width='1.5'/><path d='M10.2 10.2 13 13' stroke='%23968990' stroke-width='1.5' stroke-linecap='round'/></svg>");
  background-position: 10px 50%;
  background-repeat: no-repeat;
  background-size: 13px;
}
.search input:focus { border-color: color-mix(in srgb, #2f6feb 45%, var(--line)); outline: none; }
.sr-only { clip: rect(0 0 0 0); height: 1px; overflow: hidden; position: absolute; width: 1px; }

.gantt { display: grid; gap: 5px; padding: 4px 28px 10px; }
.gantt-row { align-items: center; display: grid; gap: 10px; grid-template-columns: 36px 1fr; }
.gantt-row > span { color: var(--ink-3); font-size: 11px; }
.gantt-track { background: linear-gradient(180deg, transparent, rgba(43,22,34,.03)); height: 12px; position: relative; }
.gantt-bar {
  border: 0;
  border-radius: 3px;
  height: 8px;
  min-width: 6px;
  opacity: .92;
  padding: 0;
  position: absolute;
  top: 2px;
}
.gantt-bar:hover, .gantt-bar.on { outline: 2px solid rgba(47, 111, 235, .35); outline-offset: 1px; }

.session-shell {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(0, 1fr);
  min-height: 0;
}
.session-shell.has-inspector { grid-template-columns: minmax(0, 1fr) min(420px, 42vw); }
.session-main { min-height: 0; overflow-y: auto; }
.log { padding: 4px 8px 48px 18px; }
.talk { display: flex; flex-direction: column; gap: 14px; padding: 18px 28px 48px; }
.artifacts { display: flex; flex-direction: column; gap: 10px; padding: 18px 28px 48px; }

.turn-mark {
  color: var(--ink-3);
  font-size: 11px;
  font-weight: 650;
  padding: 10px 10px 4px 4px;
}
.log-row {
  align-items: flex-start;
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: inset 3px 0 0 transparent;
  display: flex;
  gap: 10px;
  padding: 7px 14px 7px 10px;
  text-align: left;
  width: 100%;
}
.log-row:hover { background: #faf8f9; }
.log-row.on { background: #f4f7fd; box-shadow: inset 3px 0 0 #2f6feb; }
.log-line {
  align-items: baseline;
  display: flex;
  flex: 1;
  flex-wrap: nowrap;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  padding-top: 1px;
}
.log-head {
  color: var(--ink);
  flex: 0 1 auto;
  font-size: 13px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.log-line:not(:has(.log-detail)):not(:has(.log-result)) .log-head { flex: 1 1 auto; }
.log-detail, .log-result {
  color: var(--ink-2);
  font-size: 12.5px;
  font-style: normal;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.log-detail { color: var(--ink-3); flex: 0 1 32%; font-family: var(--mono-font); font-size: 12px; }
.log-result { flex: 1 1 0; min-width: 6em; }
.log-arrow { color: var(--ink-3); flex: 0 0 auto; }
.log-row.bad .log-result { color: var(--danger); }

.role-pill {
  border-radius: 6px;
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .02em;
  line-height: 1;
  padding: 5px 7px;
}
.role-pill.system { background: #eef0f3; color: #5b616b; }
.role-pill.user { background: #dbe8ff; color: #2154c7; }
.role-pill.context { background: #d8f3e8; color: #0f7a4d; }
.role-pill.assistant { background: #ece4ff; color: #6d3ad0; }
.role-pill.tool { background: #ffe8cc; color: #c05612; }

.talk-card {
  display: flex;
  gap: 10px;
}
.talk-body { color: var(--ink); flex: 1; font-size: 13.5px; line-height: 1.7; min-width: 0; }
.talk-body.md :deep(p) { margin: 0 0 8px; }
.talk-body.md :deep(p:last-child) { margin-bottom: 0; }
.talk-body.md :deep(table) { border-collapse: collapse; font-size: 12.5px; margin: 8px 0 12px; width: 100%; }
.talk-body.md :deep(th), .talk-body.md :deep(td) { border-bottom: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; white-space: nowrap; }
.talk-body.md :deep(th) { color: var(--ink-3); font-weight: 650; }
.talk-body.md :deep(h1), .talk-body.md :deep(h2), .talk-body.md :deep(h3) { font-size: 14px; margin: 12px 0 6px; }

.inspector {
  background: var(--paper);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.inspector-head {
  align-items: center;
  display: flex;
  gap: 8px;
  padding: 12px 14px 8px;
}
.inspector-head strong { color: var(--ink-2); flex: 1; font-size: 12.5px; font-weight: 600; }
.inspector-close {
  background: transparent;
  border: 0;
  color: var(--ink-3);
  font-size: 18px;
  height: 28px;
  line-height: 1;
  width: 28px;
}
.inspector-close:hover { color: var(--ink); }
.inspector-tabs {
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 14px;
  padding: 0 14px;
}
.inspector-tabs button {
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--ink-3);
  font-size: 12.5px;
  font-weight: 650;
  margin-bottom: -1px;
  padding: 8px 0;
}
.inspector-tabs button.on { border-bottom-color: #2f6feb; color: var(--ink); }
.inspector-body { display: flex; flex: 1; flex-direction: column; gap: 14px; min-height: 0; overflow: auto; padding: 14px 16px 24px; }
.kv { align-items: start; display: grid; gap: 12px; grid-template-columns: 52px minmax(0, 1fr); }
.kv > span { color: var(--ink-3); font-size: 12px; padding-top: 2px; }
.kv.stack { align-items: start; }
.status-text { font-size: 13px; font-weight: 650; }
.status-text.completed { color: var(--success); }
.status-text.failed { color: var(--danger); }
.status-text.running { color: var(--warning); }
.json, .plain {
  background: #faf8f9;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.55;
  margin: 0;
  max-height: 280px;
  overflow: auto;
  padding: 8px 10px;
  white-space: pre-wrap;
  word-break: break-word;
}
.json.fill, .plain.fill { flex: 1; max-height: none; }
pre.json :deep(.json-key) { color: #a21d4c; }
pre.json :deep(.json-str) { color: #1f4b3a; }
pre.json :deep(.json-num) { color: #1d4ed8; }
pre.json :deep(.json-lit) { color: #6d28d9; }
.schema-name { display: block; font-family: var(--mono-font); font-size: 13px; margin-bottom: 4px; }
.schema-desc { color: var(--ink-2); font-size: 12.5px; line-height: 1.6; }
.schema h3 { font-family: var(--mono-font); font-size: 14px; margin-bottom: 6px; }
.schema h4 { color: var(--ink-3); font-size: 12px; margin: 14px 0 8px; }
.schema p { color: var(--ink-2); font-size: 13px; line-height: 1.65; }
.schema ul { display: grid; gap: 8px; list-style: none; }
.schema li { color: var(--ink-2); font-size: 12.5px; line-height: 1.5; }
.schema li code { color: var(--ink); font-weight: 700; margin-right: 6px; }
.schema li i { color: var(--ink-3); font-style: normal; margin-right: 8px; }
.timing { display: grid; gap: 6px; }
.timing > div { display: grid; gap: 10px; grid-template-columns: 72px 1fr; }
.timing dt { color: var(--ink-3); font-size: 12px; }
.timing dd { font-size: 12.5px; }
.timing.big > div { grid-template-columns: 84px 1fr; padding: 6px 0; }
.pane-tools { display: flex; justify-content: flex-end; }
.pane-tools button {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink-2);
  font-size: 11px;
  padding: 3px 8px;
}
.result-meta { color: var(--ink-3); font-size: 12px; margin-bottom: 6px; }
.result-table-wrap { border: 1px solid var(--line); border-radius: 10px; overflow: auto; }
.result-table { border-collapse: collapse; font-size: 12px; width: 100%; }
.result-table th { background: #faf8f9; border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
.result-table td { border-bottom: 1px solid var(--line); padding: 5px 8px; }

.child-runs {
  border-bottom: 1px solid var(--line);
  padding: 14px 22px 18px;
}
.child-runs h2 { font-size: 14px; margin: 0 0 4px; }
.child-runs > p { color: var(--ink-3); font-size: 12px; margin: 0 0 10px; }
.child-grid { display: grid; gap: 8px; }
.child-card {
  align-items: center;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 12px;
  cursor: pointer;
  display: grid;
  gap: 10px;
  grid-template-columns: 10px 1fr auto;
  padding: 10px 12px;
  text-align: left;
}
.child-card:hover { border-color: var(--accent); }
.child-card b { display: block; font-size: 12.5px; }
.child-card span { color: var(--ink-3); display: block; font-size: 12px; line-height: 1.4; }
.child-card small { color: var(--ink-3); font-size: 11px; }

@media (max-width: 1040px) {
  .session-head, .session-tabs, .session-toolbar, .gantt { padding-left: 16px; padding-right: 16px; }
  .session-shell.has-inspector { grid-template-columns: minmax(0, 1fr); }
  .inspector {
    background: var(--paper);
    box-shadow: -18px 0 40px rgba(43, 22, 34, .12);
    inset: 0 0 0 auto;
    position: absolute;
    width: min(420px, 92vw);
    z-index: 5;
  }
  .session-shell { position: relative; }
  .search input { width: 150px; }
}
</style>
