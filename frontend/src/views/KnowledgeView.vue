<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/backend.js'
import { formatDate, store } from '../store.js'
import { renderMarkdown } from '../utils/markdown.js'
import NavIcon from '../components/NavIcon.vue'
import KnowledgeCandidateForm from '../components/KnowledgeCandidateForm.vue'

const route = useRoute()
const router = useRouter()
const libraryRoute = route.name
const documents = ref([])
const current = ref(null)
const selected = ref('')
const query = ref('')
const submittedQuery = ref('')
const hits = ref([])
const error = ref('')
const notice = ref('')
const busy = ref(false)
const uploading = ref(false)
const formOpen = ref(false)
const input = ref(null)
const reader = ref(null)
const sectionIndex = ref(0)
const publish = computed(() => ['admin', 'knowledge_reviewer'].includes(store.user?.role))
const sections = computed(() => current.value?.sections.map(s => ({ ...s, html: renderMarkdown(s.content) })) || [])
let sequence = 0

async function loadDocuments() {
  documents.value = await api.knowledgeDocuments()
}
async function openDocument(id, index = 0) {
  const ticket = ++sequence
  selected.value = id
  formOpen.value = false
  submittedQuery.value = ''
  busy.value = true
  error.value = ''
  try {
    const result = await api.knowledgeDocument(id)
    if (ticket !== sequence) return
    current.value = result
    busy.value = false
    await jump(Number(index) || 0)
  } catch (e) { if (ticket === sequence) error.value = e.message }
  finally { if (ticket === sequence) busy.value = false }
}
async function jump(index) {
  sectionIndex.value = Math.max(0, Math.min(index, sections.value.length - 1))
  await nextTick()
  const target = reader.value?.querySelector('[data-section="' + sectionIndex.value + '"]')
  if (target && reader.value) reader.value.scrollTop += target.getBoundingClientRect().top - reader.value.getBoundingClientRect().top - 14
}
function trackScroll() {
  if (!reader.value) return
  const top = reader.value.getBoundingClientRect().top + 36
  const blocks = [...reader.value.querySelectorAll('[data-section]')]
  sectionIndex.value = Math.max(0, blocks.findLastIndex(block => block.getBoundingClientRect().top < top))
}
function selectDocument(id, index = 0) {
  if (route.query.doc === id && Number(route.query.section || 0) === index) {
    return openDocument(id, index)
  }
  return router.push({ name: libraryRoute, query: { doc: id, section: index } })
}
watch(() => [route.query.doc, route.query.section], ([id, index]) => {
  if (route.name === libraryRoute && documents.value.length) {
    openDocument(String(id || documents.value[0].id), index)
  }
})
async function search() {
  const phrase = query.value.trim()
  if (!phrase) { clearSearch(); return }
  const ticket = ++sequence
  submittedQuery.value = phrase
  formOpen.value = false
  hits.value = []
  busy.value = true
  error.value = ''
  try {
    const result = await api.searchKnowledge(phrase)
    if (ticket === sequence) hits.value = result
  } catch (e) { if (ticket === sequence) error.value = e.message }
  finally { if (ticket === sequence) busy.value = false }
}
function clearSearch() {
  ++sequence
  query.value = ''
  submittedQuery.value = ''
  error.value = ''
  busy.value = false
  const id = selected.value || route.query.doc || documents.value[0]?.id
  if (id && current.value?.id !== id) openDocument(id, route.query.section)
}
async function upload(event) {
  const files = [...event.target.files]
  event.target.value = ''
  if (!files.length) return
  uploading.value = true
  const messages = []
  let publishedId
  for (const file of files) {
    try {
      const result = await api.uploadKnowledge(file)
      if (result.state === 'published') {
        publishedId ||= result.document_id
        messages.push(file.name + ' 已发布（v' + result.version + '）')
      } else {
        messages.push(file.name + ' 已提交审核')
      }
    } catch (e) { messages.push(file.name + ' 上传失败：' + e.message) }
  }
  notice.value = messages.join(' · ')
  try {
    if (publishedId) { await loadDocuments(); await selectDocument(publishedId) }
  } catch (e) { error.value = e.message }
  finally { uploading.value = false }
}
function showCandidate() {
  ++sequence
  busy.value = false
  formOpen.value = true
  submittedQuery.value = ''
  error.value = ''
}
onMounted(async () => {
  const ticket = sequence
  busy.value = true
  try {
    await loadDocuments()
    if (submittedQuery.value || formOpen.value || selected.value) return
    const first = String(route.query.doc || documents.value[0]?.id || '')
    if (first) await openDocument(first, route.query.section)
  } catch (e) { if (ticket === sequence) error.value = e.message }
  finally { if (ticket === sequence) busy.value = false }
})
</script>

<template>
  <main class="kb-page">
    <header class="kb-head"><h1>知识库</h1>
      <div class="kb-actions"><button class="btn-text" type="button" @click="showCandidate">提交知识候选</button>
        <button class="btn-p" type="button" :disabled="uploading" @click="input.click()">{{ uploading ? '正在上传…' : '上传 Markdown' }}</button>
        <input ref="input" type="file" hidden multiple accept=".md,.markdown,text/markdown" aria-label="选择 Markdown 文件" @change="upload" />
      </div>
    </header>
    <p class="kb-hint">{{ publish ? '上传后发布。同名文件再次上传会更新文档。' : '上传的文档经知识审核后发布。' }}</p>
    <form class="kb-search" role="search" @submit.prevent="search">
      <input v-model="query" type="search" aria-label="搜索知识库" placeholder="搜索业务术语、指标口径或文档内容" maxlength="1000" @input="!query && clearSearch()" />
      <button type="submit">搜索</button>
    </form>
    <p v-if="notice" class="kb-notice" role="status">{{ notice }}</p>
    <div class="kb-layout">
      <nav aria-label="知识文档" class="kb-index">
        <h2>文档 <small>{{ documents.length }}</small></h2>
        <button v-for="doc in documents" :key="doc.id" type="button" class="kb-doc" :class="{chosen: doc.id === selected && !submittedQuery && !formOpen}" @click="selectDocument(doc.id)">
          <NavIcon name="knowledge"/><span>{{ doc.filename }}</span>
        </button>
        <p v-if="!documents.length && !busy">暂无已发布文档</p>
      </nav>
      <section class="kb-content">
        <p v-if="error" role="alert" class="kb-error">{{ error }}</p>
        <KnowledgeCandidateForm v-if="formOpen" @close="formOpen=false" @submitted="formOpen=false" />
        <p v-else-if="busy" role="status">正在{{ submittedQuery ? '检索' : '读取' }}…</p>
        <template v-else-if="submittedQuery">
          <h2>搜索结果 <small>{{ hits.length }}</small></h2>
          <p v-if="!hits.length">没有找到与「{{ submittedQuery }}」匹配的章节。</p>
          <button v-for="hit in hits" :key="hit.document_id + ':' + hit.section" class="kb-hit" type="button" @click="selectDocument(hit.document_id, hit.section)">
            <small>{{ hit.filename }}</small><strong>{{ hit.heading }}</strong><span>{{ hit.excerpt }}</span>
          </button>
        </template>
        <template v-else-if="current && current.id===selected">
          <header class="kb-doc-head"><h2>{{ current.filename }}</h2><small>v{{ current.version }} · {{ formatDate(current.updated_at) }}</small></header>
          <div class="kb-select"><label>章节 <select :value="sectionIndex" @change="selectDocument(current.id, Number($event.target.value))"><option v-for="(s, i) in sections" :key="i" :value="i">{{ s.heading }}</option></select></label></div>
          <article ref="reader" class="kb-reader md-body" aria-label="文档原文" @scroll.passive="trackScroll">
            <section v-for="(s, i) in sections" :key="i" :data-section="i" v-html="s.html"></section>
          </article>
        </template>
        <p v-else-if="!error">上传 Markdown 文件后，可以在这里检索和阅读业务知识。</p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.kb-page{flex:1;min-height:0;overflow:auto;padding:clamp(18px,3vw,40px);color:var(--ink);background:var(--bg,#f7f7f9)}
.kb-head,.kb-actions,.kb-search,.kb-doc,.kb-doc-head{display:flex;align-items:center;gap:12px}.kb-head,.kb-doc-head{justify-content:space-between}
.kb-head h1{font-size:28px;margin:0}.kb-hint,.kb-content>p,.kb-index p{color:var(--ink-2);font-size:14px}.kb-hint{margin:6px 0 20px}
.kb-search{max-width:740px;border:1px solid var(--line);background:white;border-radius:10px;padding:5px 6px 5px 15px}.kb-search:focus-within{outline:2px solid var(--accent);outline-offset:1px}
.kb-search input{flex:1;min-width:0;padding:7px 0;border:0;outline:0;background:transparent;font:inherit}.kb-search button,.kb-select select{font:inherit;cursor:pointer;border:1px solid var(--line);border-radius:7px;background:#fff;padding:6px 12px;color:var(--ink)}
.kb-notice{font-size:13px;color:var(--ink-2);overflow-wrap:anywhere}.kb-layout{display:grid;grid-template-columns:minmax(170px,24%) minmax(0,1fr);gap:20px;margin-top:20px}
.kb-index,.kb-content{background:var(--surface,#fff);border:1px solid var(--line);border-radius:14px;padding:18px}.kb-index{align-self:start}.kb-content{min-width:0;min-height:290px}
.kb-page h2{font-size:18px;margin:0 0 12px;overflow-wrap:anywhere}.kb-page small{font-size:12px;font-weight:400;color:var(--ink-2)}.kb-doc,.kb-hit{width:100%;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer;font:inherit}
.kb-doc{padding:10px;border-radius:7px;overflow-wrap:anywhere}.kb-doc svg{width:16px;flex:0 0 16px}.kb-doc.chosen,.kb-doc:hover,.kb-hit:hover{background:var(--accent-soft,#fff2f5);color:var(--accent)}
.kb-doc-head{align-items:baseline}.kb-doc-head small{white-space:nowrap}.kb-select{margin:0 0 8px;color:var(--ink-2);font-size:12px}.kb-select select{max-width:85%}
.kb-reader{max-height:calc(100dvh - 315px);min-height:200px;overflow:auto;padding:0 14px 14px 0;line-height:1.75;overflow-wrap:anywhere}.kb-reader :deep(table){display:block;max-width:100%;overflow-x:auto}
.kb-hit{display:grid;gap:5px;padding:12px 2px;border-bottom:1px solid var(--line)}.kb-hit span{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;color:var(--ink-2);font-size:13px}
.kb-content .kb-error{color:var(--accent)}@media(max-width:750px){.kb-page{padding:12px}.kb-layout{grid-template-columns:1fr;gap:10px}.kb-index{max-height:150px;overflow:auto}.kb-head{flex-wrap:wrap}.kb-actions{gap:8px}.kb-doc-head{flex-wrap:wrap}.kb-reader{max-height:55dvh}.kb-content{padding:14px}}
</style>
