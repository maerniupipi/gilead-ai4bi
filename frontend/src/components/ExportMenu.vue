<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api/backend.js'
import { store } from '../store.js'
import { chartExportImages, saveExportBlob } from '../utils/documentExport.js'

const props = defineProps({
  source: { type: Object, required: true },
  view: { type: Object, default: () => ({}) },
  label: { type: String, default: '导出' },
  disabled: { type: Boolean, default: false },
})
const menu = ref(null)
const host = ref(null)
const panel = ref(null)
const opened = ref(false)
const position = ref({})
const busy = ref(false)
const progress = ref('')
const error = ref('')
let controller = null

function toggleMenu() {
  opened.value = menu.value.open
  if (!opened.value) return
  const rect = menu.value.getBoundingClientRect()
  position.value = {
    left: `${Math.max(8, Math.min(rect.right - 240, window.innerWidth - 248))}px`,
    top: `${rect.bottom + 242 > window.innerHeight ? Math.max(8, rect.top - 234) : rect.bottom + 8}px`,
  }
}
function closeMenu() { if (menu.value) menu.value.open = false }
function outside(event) {
  if (!host.value?.contains(event.target) && !panel.value?.contains(event.target)) closeMenu()
}

async function download(format) {
  if (busy.value || props.disabled) return
  const token = store.token
  busy.value = true
  error.value = ''
  progress.value = '正在读取分析内容…'
  menu.value.open = false
  controller = new AbortController()
  const { signal } = controller
  const selection = JSON.parse(JSON.stringify({ source: props.source, view: props.view }))
  try {
    const prepared = await api.prepareDocumentExport(selection, { signal })
    const images = await chartExportImages(prepared.charts, {
      signal, onProgress: value => { progress.value = value },
    })
    progress.value = '正在生成文件…'
    const result = await api.downloadDocumentExport({
      ...selection, format, document_key: prepared.document_key, images,
    }, { signal })
    signal.throwIfAborted()
    if (store.token === token) saveExportBlob(result.blob, result.filename)
  } catch (cause) {
    if (cause.name !== 'AbortError') error.value = cause.message || '导出失败，请重试'
  } finally {
    busy.value = false
    progress.value = ''
  }
}

watch(() => store.token, () => controller?.abort())
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('scroll', closeMenu, true)
  window.addEventListener('resize', closeMenu)
})
onBeforeUnmount(() => {
  controller?.abort()
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('scroll', closeMenu, true)
  window.removeEventListener('resize', closeMenu)
})
</script>

<template>
  <div ref="host" class="document-export" @keydown.esc="closeMenu">
    <details ref="menu" class="document-export-menu" @toggle="toggleMenu">
      <summary :aria-disabled="disabled || busy" @click="(disabled || busy) && $event.preventDefault()">↓ {{ busy ? '导出中…' : label }}</summary>
    </details>
    <Teleport to="body">
      <div v-if="opened" ref="panel" class="document-export-options" :style="position" role="group" aria-label="选择导出格式" @keydown.esc="closeMenu">
        <button type="button" @click="download('pptx')"><b>PPT</b><span>导出 PowerPoint</span></button>
        <button type="button" @click="download('xlsx')"><b>XLSX</b><span>导出 Excel 数据</span></button>
        <button type="button" @click="download('pdf')"><b>PDF</b><span>导出 PDF 报告</span></button>
        <p>PPT / PDF 每表展示前100行，长文本按版面省略。XLSX保留已查询数据。</p>
      </div>
    </Teleport>
    <span v-if="busy" class="document-export-status" role="status">{{ progress }}</span>
    <p v-if="error" class="document-export-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.document-export { position: relative; display: inline-flex; align-items: center; gap: 7px; max-width: 100%; font-size: 11px; color: var(--ink-2); }
.document-export-menu { position: relative; }
.document-export-menu summary { padding: 7px 11px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--paper); color: var(--ink-2); cursor: pointer; list-style: none; white-space: nowrap; }
.document-export-menu summary::-webkit-details-marker { display: none; }
.document-export-menu summary[aria-disabled="true"] { opacity: .55; cursor: default; }
.document-export-menu[open] summary { border-color: var(--accent); color: var(--accent); }
.document-export-options { position: fixed; z-index: 700; width: 240px; padding: 7px; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); box-shadow: 0 14px 40px #2426301a; }
.document-export-options button { display: flex; align-items: center; gap: 13px; width: 100%; padding: 11px 10px; border: 0; border-radius: 7px; color: var(--ink); background: transparent; cursor: pointer; text-align: left; }
.document-export-options button:hover { background: var(--bg); }
.document-export-options b { min-width: 35px; color: var(--accent); font-size: 10px; }
.document-export-options span { font-size: 12px; }
.document-export-options p { margin: 5px 10px 7px; color: var(--ink-3); font-size: 10px; line-height: 1.7; }
.document-export-status { max-width: 165px; font-size: 10px; }
.document-export-error { position: absolute; z-index: 71; right: 0; top: 100%; width: 260px; margin: 7px 0 0; padding: 10px; border-radius: 8px; background: var(--paper); color: var(--danger); border: 1px solid var(--line); line-height: 1.7; }
</style>
