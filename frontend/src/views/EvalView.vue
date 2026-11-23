<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { loadModels, store } from '../store.js'
import {
  canRerun,
  previewText,
  STATUS_LABEL,
} from '../eval/format.js'
import {
  clearWorkbook,
  evalBusy,
  evalItems,
  evalState,
  evalStats,
  evalWorkbook,
  exportWorkbook,
  fileMeta,
  forgetItemDetail,
  loadItemDetail,
  logEval,
  pagedItems,
  pauseEval,
  rebuildQueue,
  rerunFailed,
  rerunOne,
  restoreEval,
  saveEval,
  setEvalPage,
  startEval,
  stopEval,
  toggleSheet,
  uploadWorkbook,
} from '../eval/store.js'

const fileInput = ref(null)
const logEl = ref(null)
const openId = ref('')
const visibleLogs = computed(() => evalState.logs.slice(-80).join('\n'))

const sheetChecks = computed(() => {
  const picked = new Set(evalState.settings.selectedSheets)
  return (evalWorkbook.value?.sheets || []).map((sheet) => ({
    name: sheet.name,
    count: sheet.question_count,
    checked: picked.has(sheet.name),
  }))
})

const failedCount = computed(() => evalItems.value.filter((item) => item.status === 'failed').length)
const pauseLabel = computed(() => (evalState.pausing ? '继续' : '暂停'))
const pageLabel = computed(() => `第 ${evalState.page} / ${evalStats.value.pages} 页`)

async function toggleOpen(item) {
  if (openId.value === item.id) {
    openId.value = ''
    forgetItemDetail(item)
    return
  }
  openId.value = item.id
  await loadItemDetail(item)
}

async function refreshModels() {
  if (!store.token) return
  try { await loadModels() }
  catch (error) { logEval(`加载模型列表失败：${error.message || error}`) }
}

onMounted(async () => {
  await restoreEval()
  await refreshModels()
})

watch(() => store.token, (token) => {
  if (token) refreshModels()
})

watch(() => evalState.logs.length, async () => {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
})

async function onFile(event) {
  const file = event.target.files?.[0]
  await uploadWorkbook(file)
  if (fileInput.value) fileInput.value.value = ''
}

function pickFile() {
  fileInput.value?.click()
}

function persistSettings() {
  saveEval()
}

function onRangeChange() {
  rebuildQueue()
}

function statusClass(status) {
  return `chip ${status}`
}

function statusText(status) {
  return STATUS_LABEL[status] || status
}
</script>

<template>
  <div class="page-shell wide-page eval-page">
    <section class="panel eval-config">
      <div class="eval-bar">
        <div class="eval-group">
          <span class="eval-k">工作簿</span>
          <input ref="fileInput" class="file-hidden" type="file" accept=".xlsx" @change="onFile" />
          <button class="btn-g" type="button" @click="pickFile">上传 xlsx</button>
          <span v-if="fileMeta" class="file-name">{{ fileMeta }}</span>
          <button class="btn-g" type="button" @click="clearWorkbook">清空</button>
        </div>
        <div v-if="sheetChecks.length" class="eval-group sheets">
          <span class="eval-k">工作表</span>
          <button
            v-for="sheet in sheetChecks"
            :key="sheet.name"
            type="button"
            class="sheet-chip"
            :class="{ on: sheet.checked }"
            @click="toggleSheet(sheet.name, !sheet.checked)"
          >
            {{ sheet.name }}<em>{{ sheet.count }}</em>
          </button>
        </div>
      </div>

      <div class="eval-bar controls">
        <label class="field grow">
          <span>模型</span>
          <select v-model="evalState.settings.model" @change="persistSettings">
            <option value="">跟随当前激活模型</option>
            <option v-for="model in store.models" :key="model.id" :value="model.id">
              {{ model.name }}（{{ model.model_id }}{{ model.is_active ? ' · 激活' : '' }}）
            </option>
          </select>
        </label>
        <label class="field">
          <span>思考模式</span>
          <select v-model="evalState.settings.thinking" @change="persistSettings">
            <option value="default">跟随模型</option>
            <option value="on">开</option>
            <option value="off">关</option>
          </select>
        </label>
        <label class="field">
          <span>思考强度</span>
          <select
            v-model="evalState.settings.thinkingLevel"
            :disabled="evalState.settings.thinking !== 'on'"
            @change="persistSettings"
          >
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </label>
        <label class="field compact">
          <span>从第几题</span>
          <input v-model="evalState.settings.fromIndex" type="number" min="1" @change="onRangeChange" />
        </label>
        <label class="field compact">
          <span>到第几题</span>
          <input v-model="evalState.settings.toIndex" type="number" min="1" placeholder="全部" @change="onRangeChange" />
        </label>
        <label class="field compact">
          <span>并行数</span>
          <input v-model="evalState.settings.concurrency" type="number" min="1" max="8" :disabled="evalState.running" @change="persistSettings" />
        </label>
      </div>

      <div class="eval-actions">
        <button class="btn-p" type="button" :disabled="evalBusy" @click="startEval">开始评测</button>
        <button class="btn-g" type="button" :disabled="!evalState.running" @click="pauseEval">{{ pauseLabel }}</button>
        <button class="btn-g danger" type="button" :disabled="!evalBusy" @click="stopEval">停止</button>
        <button class="btn-g" type="button" :disabled="!evalState.batchId" @click="exportWorkbook">导出 xlsx</button>
        <button class="btn-g" type="button" :disabled="evalBusy || !failedCount" @click="rerunFailed">重跑失败项</button>
        <span class="count-chip">{{ evalStats.done }}/{{ evalStats.total }} 完成</span>
      </div>
    </section>

    <section class="panel eval-progress">
      <div class="eval-stats">
        <div class="stat"><em>队列</em><b>{{ evalStats.total }}</b></div>
        <div class="stat"><em>待跑</em><b>{{ evalStats.queued }}</b></div>
        <div class="stat"><em>完成</em><b>{{ evalStats.done }}</b></div>
        <div class="stat"><em>失败</em><b>{{ evalStats.fail }}</b></div>
        <div class="stat"><em>当前</em><b>{{ evalStats.now }}</b></div>
      </div>
      <div class="meter"><span :style="{ width: evalStats.meter + '%' }"></span></div>
      <pre ref="logEl" class="eval-log">{{ visibleLogs }}</pre>
    </section>

    <section class="panel eval-table-panel">
      <div class="panel-head">
        <h2>题目</h2>
        <div v-if="evalStats.pages > 1" class="pager">
          <button class="btn-g tiny" type="button" :disabled="evalState.page <= 1" @click="setEvalPage(evalState.page - 1)">上一页</button>
          <span>{{ pageLabel }}</span>
          <button class="btn-g tiny" type="button" :disabled="evalState.page >= evalStats.pages" @click="setEvalPage(evalState.page + 1)">下一页</button>
        </div>
      </div>
      <p v-if="evalState.hydrating" class="empty-inline">正在恢复本机评测集…</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th><th>工作表</th><th>分类</th><th>问题</th><th>状态</th>
              <th>最终结果</th><th>持续时间</th>
              <th class="op">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in pagedItems" :key="item.id">
              <tr>
                <td>{{ item.index }}</td>
                <td>{{ item.sheet }}</td>
                <td>{{ item.category }}</td>
                <td class="q">{{ item.question }}</td>
                <td><span :class="statusClass(item.status)">{{ statusText(item.status) }}</span></td>
                <td><div class="clamp">{{ previewText(item.answer || item.error, 120) }}</div></td>
                <td>{{ item.duration }}</td>
                <td class="op">
                  <button class="btn-g tiny" type="button" @click="toggleOpen(item)">{{ openId === item.id ? '收起' : '详情' }}</button>
                  <button class="btn-g tiny" type="button" :disabled="!canRerun(item)" @click="rerunOne(item)">重跑</button>
                </td>
              </tr>
              <tr v-if="openId === item.id" class="detail-row">
                <td colspan="8">
                  <div class="detail-grid">
                    <section><b>澄清</b><pre>{{ item.clarify || '—' }}</pre></section>
                    <section><b>SQL</b><pre>{{ item.sql || '—' }}</pre></section>
                    <section><b>实验室</b><pre>{{ item.labs || '—' }}</pre></section>
                    <section><b>最终结果</b><pre>{{ item.answer || item.error || '—' }}</pre></section>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <p v-if="!evalItems.length && !evalState.hydrating" class="empty-inline">还没有题目。先上传工作簿。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.eval-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 0 auto;
  max-width: 1400px;
  width: 100%;
}
.eval-config { position: relative; }
.eval-config,
.eval-progress,
.eval-table-panel { padding: 16px 18px 18px; }
.eval-bar {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 14px;
}
.eval-bar + .eval-bar,
.eval-actions {
  border-top: 1px solid var(--line);
  margin-top: 14px;
  padding-top: 14px;
}
.eval-bar.controls {
  display: grid;
  grid-template-columns: minmax(220px, 2fr) minmax(128px, 1fr) minmax(128px, 1fr) 108px 108px 108px;
}
.eval-config select:disabled,
.eval-config input:disabled {
  background: #f6f3f4;
  color: var(--ink-3);
}
.eval-config input[type='number'] { -moz-appearance: textfield; }
.eval-config input[type='number']::-webkit-inner-spin-button,
.eval-config input[type='number']::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.eval-group {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.eval-group.sheets { flex: 1; }
.eval-k {
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.file-hidden {
  height: 0;
  opacity: 0;
  pointer-events: none;
  position: absolute;
  width: 0;
}
.file-name {
  color: var(--ink);
  font-size: 13px;
  font-weight: 550;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sheet-chip {
  align-items: center;
  background: #fbf8f9;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--ink-2);
  display: inline-flex;
  font-size: 12px;
  font-weight: 600;
  gap: 6px;
  min-height: 32px;
  padding: 4px 12px;
}
.sheet-chip em {
  color: var(--ink-3);
  font-style: normal;
  font-weight: 500;
}
.sheet-chip:hover { border-color: var(--accent); color: var(--accent-dark); }
.sheet-chip.on {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
  color: var(--accent-dark);
}
.eval-config .field { min-width: 0; }
.eval-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.eval-actions .count-chip { margin-left: auto; }
.eval-stats { display: grid; gap: 10px; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.stat { background: #fbf8f9; border-radius: 12px; padding: 12px; }
.stat em { color: var(--ink-3); display: block; font-size: 12px; font-style: normal; }
.stat b { font-size: 22px; font-weight: 650; letter-spacing: -.03em; }
.meter { background: #eadfe4; border-radius: 99px; height: 8px; margin: 14px 0 0; overflow: hidden; }
.meter span { background: var(--accent); display: block; height: 100%; width: 0; }
.eval-log {
  background: #1c1418;
  border-radius: 12px;
  color: #f6e8ef;
  font: 12px/1.5 var(--mono-font);
  margin-top: 12px;
  max-height: 160px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}
.table-wrap { margin-top: 4px; max-height: 62vh; overflow: auto; }
table { border-collapse: collapse; min-width: 920px; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #fbf8f9; color: var(--ink-3); font-size: 12px; position: sticky; top: 0; z-index: 1; }
th.op, td.op { background: var(--paper); position: sticky; right: 0; white-space: nowrap; z-index: 2; }
th.op { background: #fbf8f9; z-index: 3; }
td.q { max-width: 280px; }
.clamp {
  font-family: var(--mono-font);
  font-size: 12px;
  line-height: 1.5;
  max-width: 280px;
  max-height: 7.5em;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.chip {
  border-radius: 999px;
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  white-space: nowrap;
}
.queued { background: #f1eef0; color: var(--ink-2); }
.running { background: #e8f1ff; color: #1d4f91; }
.clarify { background: #fff3d6; color: var(--warning); }
.done { background: #e5f4ec; color: var(--success); }
.failed { background: #fde8e8; color: var(--danger); }
.paused { background: #eee; color: var(--ink-2); }
.tiny { font-size: 12px; min-height: 28px; padding: 4px 10px; }
.pager { align-items: center; color: var(--ink-2); display: flex; font-size: 12px; gap: 8px; }
.detail-row td { background: #fbf8f9; }
.detail-grid { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
.detail-grid section { min-width: 0; }
.detail-grid b { color: var(--ink-3); display: block; font-size: 11px; margin-bottom: 4px; }
.detail-grid pre {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  font: 12px/1.5 var(--mono-font);
  max-height: 220px;
  overflow: auto;
  padding: 8px 10px;
  white-space: pre-wrap;
  word-break: break-word;
}
@media (max-width: 960px) {
  .detail-grid { grid-template-columns: 1fr; }
  .eval-bar.controls {
    grid-template-columns: 1fr 1fr;
  }
  .eval-bar.controls .grow { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .eval-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eval-actions .count-chip { margin-left: 0; }
}
</style>
