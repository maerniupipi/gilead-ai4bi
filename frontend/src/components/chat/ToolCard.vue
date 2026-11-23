<script setup>
import { computed, defineAsyncComponent, ref } from 'vue'
import { showToast } from '../../store.js'
import { downloadRunExport, exportIdsFromHref } from '../../utils/xlsxDownload.js'
import SubAgentMark from './SubAgentMark.vue'

const NestedTrace = defineAsyncComponent(() => import('./AgentTrace.vue'))

const props = defineProps({ tool: { type: Object, required: true } })
const isAgentCall = computed(() => Boolean(props.tool.child) || props.tool.kind === 'agent')
const downloading = ref(false)

const stateIcon = computed(() => {
  if (props.tool.state === 'running') return '…'
  return props.tool.ok ? '✓' : '✕'
})

const argLines = computed(() => Object.entries(props.tool.arguments || {}).map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`))

const table = computed(() => {
  if (props.tool.name === 'export_xlsx') return null
  const preview = props.tool.preview
  if (!preview?.columns?.length) return null
  return { columns: preview.columns, rows: (preview.rows || []).slice(0, 30), rowCount: preview.row_count ?? (preview.rows || []).length }
})

const xlsxExport = computed(() => {
  const preview = props.tool.preview
  if (props.tool.name !== 'export_xlsx' || !preview?.download_path) return null
  return {
    filename: preview.filename || '查询结果.xlsx',
    title: preview.title || '',
    summary: preview.summary || '',
    rowCount: preview.row_count,
    downloadPath: preview.download_path,
  }
})

async function downloadXlsx() {
  const ids = exportIdsFromHref(xlsxExport.value?.downloadPath)
  if (!ids || downloading.value) return
  downloading.value = true
  try {
    await downloadRunExport(ids.runId, ids.exportId, xlsxExport.value.filename)
  } catch (error) {
    showToast(error.message || '下载失败')
  } finally {
    downloading.value = false
  }
}

const candidates = computed(() => props.tool.preview?.candidates || [])

const LOOP_PROMPT_LABELS = {
  loop_prompt_1: '术语词表',
  loop_prompt_2: '口径确认',
  loop_prompt_3: '时间基准',
  loop_prompt_4: 'KPI 公式',
}

const loopPrompts = computed(() => Object.entries(props.tool.preview?.loop_prompts || {})
  .filter(([, value]) => value)
  .map(([key, value]) => ({ key, label: LOOP_PROMPT_LABELS[key] || key, value })))

const memorySave = computed(() => {
  const preview = props.tool.preview
  if (props.tool.name !== 'memory_save' || !preview?.content) return null
  return {
    heading: preview.scope === 'review' ? '提交知识审核 · 人工审核后生效' : '写入个人记忆 · 立即生效',
    meta: [preview.scope === 'review' && preview.title, preview.category]
      .filter(Boolean)
      .join(' · '),
    content: preview.content,
    entryId: preview.entry_id || '',
  }
})
</script>

<template>
  <article :class="['tool-card', tool.tone, tool.state, { bad: tool.ok === false }]">
    <button class="tool-head" type="button" @click="tool.open = !tool.open">
      <span class="tool-state">{{ stateIcon }}</span>
      <span class="tool-label"><SubAgentMark v-if="isAgentCall" />{{ tool.label }}</span>
      <span class="tool-summary">{{ tool.summary }}</span>
      <span class="tool-chev">{{ tool.open ? '−' : '+' }}</span>
    </button>
    <div v-if="tool.open" class="tool-body">
      <div v-if="tool.name === 'ask_lab' && tool.preview?.lab_session_id" class="tool-part">
        <b>实验室会话 ID · 可用于实验室侧溯源</b>
        <pre class="lab-session-id">{{ tool.preview.lab_session_id }}</pre>
      </div>
      <div v-if="isAgentCall && tool.child" class="tool-part nested-agent">
        <NestedTrace :msg="tool.child" nested :agent-name="tool.child.agentName || tool.label" />
      </div>
      <div v-if="argLines.length && !tool.child" class="tool-part">
        <b>参数</b>
        <pre>{{ argLines.join('\n') }}</pre>
      </div>
      <div v-if="tool.preview?.sql && !tool.child" class="tool-part">
        <b>SQL</b>
        <pre>{{ tool.preview.sql }}</pre>
      </div>
      <div v-if="xlsxExport" class="tool-part">
        <b>完整结果工作簿</b>
        <p v-if="xlsxExport.title" class="xlsx-title">{{ xlsxExport.title }}</p>
        <p class="xlsx-meta">
          <template v-if="xlsxExport.summary">{{ xlsxExport.summary }} · </template>
          共 {{ xlsxExport.rowCount ?? '—' }} 行
        </p>
        <button class="xlsx-dl" type="button" :disabled="downloading" @click="downloadXlsx">
          {{ downloading ? '正在下载…' : `下载 ${xlsxExport.filename}` }}
        </button>
      </div>
      <div v-if="table" class="tool-part">
        <b>结果 · 共 {{ table.rowCount }} 行</b>
        <div class="tool-table-wrap">
          <table class="tool-table">
            <thead><tr><th v-for="column in table.columns" :key="column">{{ column }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, index) in table.rows" :key="index">
                <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-if="memorySave" class="tool-part">
        <b>{{ memorySave.heading }}<span v-if="memorySave.meta"> · {{ memorySave.meta }}</span></b>
        <pre>{{ memorySave.content }}</pre>
      </div>
      <div v-if="loopPrompts.length" class="tool-part">
        <b>随实验室调用传递的知识上下文 · loop_prompt 1-5</b>
        <div v-for="slot in loopPrompts" :key="slot.key" class="loop-slot">
          <em>{{ slot.label }} · {{ slot.key }}</em>
          <pre>{{ slot.value }}</pre>
        </div>
      </div>
      <div v-if="candidates.length" class="tool-part">
        <b>候选 SQL</b>
        <pre v-for="(candidate, index) in candidates" :key="index">候选 {{ candidate.candidate_no ?? index + 1 }}：{{ candidate.sql }}</pre>
      </div>
      <div v-if="tool.output && !table" class="tool-part">
        <b>{{ tool.ok === false ? '错误信息' : (tool.child ? '返回给调用方' : '输出') }}</b>
        <pre class="tool-output">{{ tool.output }}</pre>
      </div>
    </div>
  </article>
</template>

<style scoped>
.tool-card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; margin: 6px 0; }
.tool-head { align-items: baseline; background: transparent; border: 0; cursor: pointer; display: flex; gap: 8px; padding: 8px 10px; text-align: left; width: 100%; }
.tool-state { color: var(--ink-3); flex: 0 0 14px; font: 700 12px var(--mono-font); text-align: center; }
.tool-card.done .tool-state { color: var(--success); }
.tool-card.bad .tool-state { color: var(--danger); }
.tool-card.running .tool-state { animation: toolPulse 1s ease-in-out infinite; color: var(--accent); }
@keyframes toolPulse { 50% { opacity: .25; } }
.tool-label {
  align-items: center;
  border: 1px solid currentColor;
  border-radius: 6px;
  display: inline-flex;
  flex: 0 0 auto;
  font: 700 9px/1.6 var(--mono-font);
  gap: 4px;
  letter-spacing: .1em;
  padding: 0 5px;
}
.tool-card.lab .tool-label { color: var(--navy); }
.tool-card.sql .tool-label { color: var(--gold); }
.tool-card.xlsx .tool-label { color: var(--navy); }
.xlsx-title { color: var(--ink); font-size: 13px; font-weight: 650; margin: 0 0 4px; }
.xlsx-meta { color: var(--ink-2); font-size: 12px; margin: 0 0 8px; }
.xlsx-dl {
  background: var(--accent);
  border: 0;
  border-radius: 10px;
  color: #fff;
  font-size: 12.5px;
  font-weight: 650;
  padding: 7px 12px;
}
.xlsx-dl:hover { background: var(--accent-dark); }
.tool-card.knowledge .tool-label { color: var(--success); }
.tool-card.memory .tool-label { color: #5a43c9; }
.tool-card.ask .tool-label { color: var(--accent); }
.tool-card.agent {
  background: #f3f8f8;
  border-color: color-mix(in srgb, var(--cyan) 40%, var(--line));
}
.tool-card.agent .tool-label { color: #2d7a7c; }
.tool-card:not(.lab):not(.sql):not(.xlsx):not(.knowledge):not(.memory):not(.ask):not(.agent) .tool-label { color: var(--ink-2); }
.nested-agent { background: transparent; }
.tool-summary { color: var(--ink-2); flex: 1 1 auto; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tool-chev { color: var(--ink-3); font: 700 12px var(--mono-font); }
.tool-body { border-top: 1px dashed var(--line); padding: 8px 10px 10px; }
.tool-part { margin-bottom: 8px; }
.tool-part:last-child { margin-bottom: 0; }
.tool-part > b { color: var(--ink-3); display: block; font: 700 9px var(--mono-font); letter-spacing: .12em; margin-bottom: 4px; text-transform: uppercase; }
.lab-session-id { color: var(--navy); user-select: all; }
.tool-part pre { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; font-size: 11.5px; line-height: 1.55; margin: 0; max-height: 260px; overflow: auto; padding: 8px 10px; white-space: pre-wrap; word-break: break-all; }
.tool-output { max-height: 320px; }
.loop-slot { margin-bottom: 6px; }
.loop-slot:last-child { margin-bottom: 0; }
.loop-slot > em { color: var(--ink-2); display: block; font: 600 10.5px/1.6 var(--mono-font); margin: 4px 0 2px; }
.tool-table-wrap { max-height: 300px; overflow: auto; border: 1px solid var(--line); border-radius: 12px; }
.tool-table { border-collapse: collapse; font-size: 11.5px; width: 100%; }
.tool-table th { background: var(--paper); border-bottom: 1px solid var(--line-strong); font-weight: 700; padding: 5px 8px; position: sticky; text-align: left; top: 0; }
.tool-table td { border-bottom: 1px solid var(--line); padding: 4px 8px; }
</style>
