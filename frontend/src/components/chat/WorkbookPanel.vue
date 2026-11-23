<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../../api/backend.js'
import { currentChatbot, loadChatbots, showToast, store } from '../../store.js'
import { formatWorkbookSize, validateWorkbookSelection, uploadWorkbookReliably, waitForWorkbookUpload, workbookUploadErrorMessage } from '../../utils/workbooks.js'

const props = defineProps({ modal: Boolean, disabled: Boolean })
const emit = defineEmits(['close', 'busy'])
const bot = computed(currentChatbot)
const books = computed(() => bot.value?.workbooks || [])
const fileInput = ref(null)
const uploadButton = ref(null)
const panel = ref(null)
const working = ref(false)
const dragging = ref(false)
const progress = ref('')
const errors = ref([])
const locked = computed(() => working.value || props.disabled || !store.token)
let previousFocus
let mounted = true

function busy(value) { working.value = value; emit('busy', value) }
function close() { if (!working.value) emit('close') }
function escape(event) { if (props.modal && event.key === 'Escape') close() }
function trapFocus(event) {
  if (!props.modal || event.key !== 'Tab') return
  const controls = [...event.currentTarget.querySelectorAll('button:not(:disabled), input:not([hidden]), summary, [tabindex="0"]')]
    .filter(element => element.getClientRects().length)
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(() => {
  if (props.modal) { previousFocus = document.activeElement; nextTick(() => panel.value?.querySelector('button:not(:disabled)')?.focus()) }
  document.addEventListener('keydown', escape)
  void resumeUploads()
})
onUnmounted(() => { mounted = false; document.removeEventListener('keydown', escape); if (props.modal) previousFocus?.focus() })

function uploadOptions(botId, owner, filename) {
  return {
    lookup: id => api.workbookUpload(botId, id),
    isCurrent: () => mounted && store.user?.id === owner && store.chatbotId === botId,
    onStatus: message => { progress.value = `${filename}：${message}` },
  }
}
function addWorkbook(result) {
  if (!result) return
  const current = currentChatbot()
  if (!current) return
  current.workbooks = [...(current.workbooks || []).filter(book => book.id !== result.id), result]
  current.workbook_ids = current.workbooks.map(book => book.id)
}
async function resumeUploads() {
  if (!store.token || working.value) return
  const botId = store.chatbotId, owner = store.user?.id
  const options = uploadOptions(botId, owner, '')
  busy(true)
  progress.value = '正在检查上传状态…'
  try {
    const { items } = await api.pendingWorkbookUploads(botId)
    if (!options.isCurrent()) return
    for (const upload of items) {
      if (!options.isCurrent()) break
      try { addWorkbook(await waitForWorkbookUpload(upload, uploadOptions(botId, owner, upload.filename))) }
      catch (error) {
        if (!options.isCurrent()) break
        errors.value.push(`${upload.filename}：${workbookUploadErrorMessage(error)}`)
        if (error.status === 401) break
      }
    }
    if (items.length && options.isCurrent()) await loadChatbots()
  } catch (error) {
    if (options.isCurrent()) errors.value = [workbookUploadErrorMessage(error)]
  } finally { progress.value = ''; busy(false) }
}

async function upload(files) {
  if (locked.value || !files.length) return
  errors.value = []
  const validation = validateWorkbookSelection(files, books.value.length)
  if (validation) { errors.value = [validation]; return }
  const botId = store.chatbotId, owner = store.user?.id
  busy(true)
  let completed = 0
  try {
    for (const [index, file] of files.entries()) {
      if (store.user?.id !== owner || store.chatbotId !== botId) break
      const options = uploadOptions(botId, owner, `${index + 1} / ${files.length} ${file.name}`)
      try {
        const result = await uploadWorkbookReliably(file, {
          ...options, begin: (selected, id) => api.uploadWorkbook(botId, selected, id),
        })
        if (!result || !options.isCurrent()) break
        addWorkbook(result)
        completed += 1
      } catch (error) {
        if (!options.isCurrent()) break
        errors.value.push(`${file.name}：${workbookUploadErrorMessage(error)}`)
        if (error.status === 401) break
      }
    }
    if (mounted && store.user?.id === owner && store.chatbotId === botId) {
      await loadChatbots()
      if (completed) showToast(`已上传 ${completed} 个文件，可以开始问数`)
    }
  } finally { progress.value = ''; busy(false) }
}
function selectFiles(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  void upload(files)
}
function dropFiles(event) { dragging.value = false; void upload([...event.dataTransfer.files]) }
async function remove(book) {
  if (locked.value) return
  const botId = store.chatbotId, owner = store.user?.id
  busy(true)
  errors.value = []
  try {
    await api.removeWorkbook(botId, book.id)
    if (store.user?.id === owner) { await loadChatbots(); showToast('文件已移除，已保存的看板快照仍可查看') }
  } catch (error) { errors.value = [error.message] }
  finally { busy(false) }
}
</script>

<template>
  <div :class="modal ? 'files-veil' : 'files-inline'" @click.self="modal && close()">
    <section ref="panel" class="files-panel" :class="{ drawer: modal }" :role="modal ? 'dialog' : 'region'" :aria-modal="modal || undefined" aria-labelledby="files-heading" :aria-busy="working" @keydown="trapFocus">
      <header class="files-heading">
        <div><p class="files-kicker">YOUR DATA, YOUR ANSWERS</p><h1 id="files-heading">{{ modal ? '管理我的文件' : books.length ? '数据已就位，开始提问吧' : '上传 Excel，让数据开口' }}</h1><p class="files-intro">{{ modal ? '这些文件仅用于当前账号的问数分析。' : '从表格到答案，再将值得关注的图表加入看板。' }}</p></div>
        <button v-if="modal" class="files-close" type="button" aria-label="关闭文件管理" :disabled="working" @click="close">×</button>
      </header>
      <div class="upload-zone" :class="{ dragging, locked }" @dragover.prevent="!locked && (dragging = true)" @dragleave.prevent="dragging = false" @drop.prevent="dropFiles">
        <span class="file-symbol" aria-hidden="true"><svg viewBox="0 0 32 36" fill="none"><path d="M6 1h14l8 8v23a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V4a3 3 0 0 1 3-3Z" stroke="currentColor" stroke-width="1.5"/><path d="M20 1v9h8M10 17l9 10m0-10-9 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span>
        <div class="upload-copy"><b>{{ books.length >= 10 ? '文件数量已达上限' : '拖入 XLSX 文件，或点击选择' }}</b><span>最多 10 个文件 · 每个不超过 10 MB · 每个最多 5 个 sheet</span></div>
        <input ref="fileInput" type="file" accept=".xlsx" multiple hidden @change="selectFiles" />
        <button ref="uploadButton" type="button" class="btn-p" :disabled="locked || books.length >= 10" @click="fileInput?.click()">{{ working ? '处理中…' : '上传 XLSX' }}<span aria-hidden="true">↑</span></button>
      </div>
      <p class="upload-tip">首行为字段名；读取已保存的单元格值，公式请先在 Excel 中计算并保存。</p>
      <div v-if="working" class="upload-progress" role="status"><i></i>{{ progress || '正在更新文件…' }}</div>
      <ul v-if="errors.length" class="file-errors" role="alert"><li v-for="error in errors" :key="error">{{ error }}</li></ul>
      <div class="files-list-head"><h2>我的数据文件 <span>{{ books.length }} / 10</span></h2><span>{{ books.length ? '展开查看字段与数据预览' : '上传后自动解析工作表' }}</span></div>
      <div v-if="!books.length" class="files-empty"><span aria-hidden="true">01 — 02 — 03</span><p>上传文件 <i>→</i> 自然语言问数 <i>→</i> 图表加入看板</p></div>
      <div v-for="book in books" :key="book.id" class="data-file">
        <div class="data-file-head"><span class="xlsx-badge">X</span><div><b>{{ book.filename }}</b><small>{{ formatWorkbookSize(book.bytes) }} · {{ book.sheets?.length || 0 }} 个 sheet · {{ book.row_count.toLocaleString() }} 行数据</small></div><span class="file-ready">可问数</span><button type="button" class="remove-file" :disabled="locked" :aria-label="`移除 ${book.filename}`" @click="remove(book)">移除</button></div>
        <details v-for="sheet in book.sheets" :key="sheet.table" class="data-sheet"><summary>{{ sheet.name }}<span>{{ sheet.columns.length }} 个字段 · {{ sheet.row_count.toLocaleString() }} 行</span></summary><div class="sheet-scroll" tabindex="0" :aria-label="`${sheet.name} 前五行数据`"><table><thead><tr><th v-for="column in sheet.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in sheet.preview" :key="index"><td v-for="(cell, ci) in row" :key="ci">{{ cell ?? '—' }}</td></tr></tbody></table></div></details>
      </div>
      <p class="files-privacy">文件按账号保存；刷新或新建对话后仍可使用。</p>
    </section>
  </div>
</template>

<style scoped>
.files-inline{max-width:1000px;margin:0 auto 24px;padding:34px 26px 0}.files-panel{color:var(--ink);min-width:0}.files-heading{display:flex;justify-content:space-between;gap:20px;margin-bottom:26px}.files-kicker{font:600 9px var(--mono-font);letter-spacing:2.2px;color:var(--accent);margin:0 0 13px}.files-heading h1{font-size:29px;letter-spacing:-1px;line-height:1.3;margin:0 0 10px;font-weight:650}.files-intro{font-size:12px;line-height:1.7;color:var(--ink-2);margin:0}.upload-zone{display:flex;align-items:center;gap:20px;background:var(--paper);border:1px dashed color-mix(in srgb,var(--accent) 32%,var(--line));border-radius:16px;padding:25px 24px;transition:border-color .16s,background .16s}.upload-zone.dragging{background:var(--accent-soft);border-color:var(--accent)}.file-symbol{color:var(--accent);display:grid;place-items:center;width:46px;flex:none}.file-symbol svg{height:43px;width:38px}.upload-copy{display:flex;flex-direction:column;gap:9px;flex:1;min-width:0}.upload-copy b{font-size:14px;font-weight:600}.upload-copy span{font-size:10px;color:var(--ink-3);line-height:1.8}.upload-zone .btn-p{font-size:12px;white-space:nowrap;display:flex;gap:19px;align-items:center;padding:12px 17px}.upload-zone .btn-p span{font-size:17px}.upload-tip{font-size:10px;color:var(--ink-3);line-height:1.8;margin:10px 3px 25px}.files-list-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:20px 0 13px}.files-list-head h2{font-size:12px;font-weight:600;margin:0}.files-list-head h2 span{font:10px var(--mono-font);color:var(--accent);margin-left:8px}.files-list-head>span{font-size:9px;color:var(--ink-3)}.files-empty{border:1px solid var(--line);border-radius:12px;text-align:center;padding:23px 12px;background:var(--paper)}.files-empty>span{font:9px var(--mono-font);letter-spacing:4px;color:var(--accent);opacity:.6}.files-empty p{font-size:11px;color:var(--ink-2);margin:12px 0 0}.files-empty i{font-style:normal;color:var(--ink-3);margin:0 12px}.data-file{border:1px solid var(--line);border-radius:12px;background:var(--paper);margin-bottom:10px;overflow:hidden}.data-file-head{display:flex;align-items:center;gap:12px;padding:15px 16px}.xlsx-badge{background:#edf5f0;color:#387254;border:1px solid #dfebe3;display:grid;place-items:center;font:600 17px Georgia,serif;width:32px;height:37px;border-radius:7px;flex:none}.data-file-head>div{flex:1;min-width:0}.data-file-head b{font-size:12px;font-weight:600;display:block;overflow-wrap:anywhere}.data-file-head small{display:block;font-size:10px;color:var(--ink-3);margin-top:5px}.file-ready{font-size:9px;color:var(--success);white-space:nowrap}.remove-file{border:0;background:transparent;font-size:10px;color:var(--ink-3);cursor:pointer;padding:8px}.remove-file:hover{color:var(--accent)}.data-sheet{border-top:1px solid var(--line)}.data-sheet summary{padding:11px 16px;font-size:11px;color:var(--ink-2);cursor:pointer}.data-sheet summary span{font-size:9px;color:var(--ink-3);margin-left:12px}.sheet-scroll{padding:0 16px 14px;overflow:auto;max-height:230px}.sheet-scroll table{border-collapse:collapse;white-space:nowrap;min-width:100%;font-size:10px;text-align:left}.sheet-scroll th,.sheet-scroll td{padding:9px 13px;border-bottom:1px solid var(--line)}.sheet-scroll th{font-weight:500;color:var(--ink-2);background:var(--bg)}.files-privacy{font-size:9px;color:var(--ink-3);margin:14px 0 0}.files-veil{position:fixed;inset:0;background:#211f2855;backdrop-filter:blur(4px);z-index:1000;display:flex;justify-content:flex-end}.drawer{background:var(--bg);width:680px;max-width:100%;height:100dvh;overflow:auto;padding:32px;box-sizing:border-box;box-shadow:-15px 0 50px #211f281c}.files-close{border:1px solid var(--line);background:var(--paper);border-radius:9px;cursor:pointer;color:var(--ink-3);height:30px;width:30px;font-size:23px;flex:none}.drawer .files-heading h1{font-size:23px}.drawer .upload-zone{gap:14px;padding:19px 16px}.drawer .upload-copy b{font-size:12px}.upload-progress{display:flex;gap:9px;align-items:center;font-size:11px;color:var(--accent);padding:12px 0;overflow-wrap:anywhere}.upload-progress i{height:6px;width:6px;background:currentColor;border-radius:50%;flex:none;animation:pulse 1s ease-in-out infinite}.file-errors{padding:12px 16px 12px 28px;font-size:11px;color:var(--danger);background:#fff2f2;border:1px solid #f0d7d7;border-radius:10px;line-height:1.8;overflow-wrap:anywhere}button:disabled{opacity:.5;cursor:default}.files-panel :focus-visible{outline:2px solid var(--accent);outline-offset:3px}@keyframes pulse{50%{opacity:.3}}@media(max-width:700px){.files-inline{padding:24px 16px 0}.files-heading h1{font-size:24px}.upload-zone{flex-wrap:wrap;padding:20px 16px;gap:14px}.upload-zone .btn-p{width:100%;justify-content:center}.upload-copy{flex-basis:calc(100% - 65px)}.upload-copy span{font-size:9px}.file-symbol{width:35px}.files-list-head>span{display:none}.files-empty i{margin:0 5px}.files-empty p{font-size:10px}.drawer{padding:25px 18px}.file-ready{display:none}.data-file-head{padding:13px}.data-sheet summary span{display:block;margin-top:6px;margin-left:16px}}@media(prefers-reduced-motion:reduce){.upload-progress i{animation:none}.upload-zone{transition:none}}
</style>
