<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { renderMarkdown } from '../utils/markdown.js'
import { TEMPLATE, categoryLabel, compose, parse, reconcile, sortEntries } from '../utils/memoryDoc.js'
import { formatDate, showToast, store } from '../store.js'

const entries = ref([])
const loading = ref(true)
const saving = ref(false)
const editing = ref(false)
const draft = ref('')
const historyById = reactive({})
const historyOpen = ref(false)

const activeEntries = computed(() => sortEntries(entries.value.filter(entry => entry.state !== 'revoked')))
const isEmpty = computed(() => !activeEntries.value.length)
const documentText = computed(() => (isEmpty.value ? TEMPLATE : compose(activeEntries.value)))
const rendered = computed(() => renderMarkdown(documentText.value))
const ownerName = computed(() => store.user?.display_name || store.user?.username || '当前用户')

async function reload() {
  loading.value = true
  try { entries.value = await api.memory() }
  catch (error) { showToast('记忆加载失败：' + error.message) }
  finally { loading.value = false }
}

function startEdit() {
  draft.value = documentText.value
  editing.value = true
}

async function save() {
  if (saving.value) return
  const wanted = parse(draft.value)
  if (wanted.length > 200) { showToast('条目过多，请精简到 200 条以内'); return }
  const plan = reconcile(wanted, activeEntries.value)
  if (!plan.create.length && !plan.update.length && !plan.revoke.length) {
    editing.value = false
    return
  }
  saving.value = true
  try {
    for (const { entry, content } of plan.update) await api.updateMemory(entry.id, { category: entry.category, content })
    for (const item of plan.create) await api.addMemory(item)
    for (const entry of plan.revoke) await api.revokeMemory(entry.id)
    editing.value = false
    Object.keys(historyById).forEach(key => delete historyById[key])
    showToast(`已保存：新增 ${plan.create.length} · 更新 ${plan.update.length} · 移除 ${plan.revoke.length}`)
    await reload()
  } catch (error) { showToast('保存失败：' + error.message) }
  finally { saving.value = false }
}

async function toggleHistory(entry) {
  if (historyById[entry.id]) {
    delete historyById[entry.id]
    return
  }
  historyById[entry.id] = { loading: true, items: [] }
  try { historyById[entry.id] = { loading: false, items: await api.memoryHistory(entry.id) } }
  catch (error) {
    delete historyById[entry.id]
    showToast('历史版本加载失败：' + error.message)
  }
}

onMounted(reload)
</script>

<template>
  <div class="page-shell">
    <header class="page-head">
      <div>
        <div class="eyebrow">只属于你</div><h1>个人记忆</h1>
        <p>只属于 {{ ownerName }} 的显式偏好与业务口径，每次提问都会随上下文召回。</p>
      </div>
      <div class="head-actions">
        <span class="count-chip">{{ activeEntries.length }} 条有效</span>
        <button v-if="!editing" class="btn-p" @click="startEdit">编辑</button>
        <template v-else>
          <button class="btn-g" :disabled="saving" @click="editing = false">取消</button>
          <button class="btn-p" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </template>
      </div>
    </header>

    <div v-if="loading" class="loading-state">正在装载个人上下文…</div>
    <template v-else>
      <article class="panel memory-doc">
        <header class="memory-doc-head">
          <div><span>记忆稿</span><h2>{{ ownerName }}</h2></div>
          <small v-if="isEmpty && !editing">默认模板 · 尚未保存</small>
          <small v-else-if="!editing">最近更新 {{ formatDate(activeEntries[activeEntries.length - 1]?.created_at) }}</small>
          <small v-else>一行一条；<code>##</code> 标题分类，<code>-</code> 开头是一条记忆</small>
        </header>
        <textarea v-if="editing" v-model="draft" class="memory-editor" rows="22" spellcheck="false"></textarea>
        <div v-else :class="['md-body', { placeholder: isEmpty }]" v-html="rendered"></div>
        <p v-if="isEmpty && !editing" class="form-hint">这是默认模板，还没有写入任何记忆。点「编辑」按自己的口径改写并保存后才会生效。</p>
      </article>

      <section v-if="activeEntries.length" class="panel history-panel">
        <div class="panel-head">
          <div><span>版本</span><h2>条目与版本</h2></div>
          <button class="btn-text" @click="historyOpen = !historyOpen">{{ historyOpen ? '收起' : '展开' }}</button>
        </div>
        <template v-if="historyOpen">
          <article v-for="entry in activeEntries" :key="entry.id" class="ledger-row">
            <div class="ledger-index">{{ categoryLabel(entry.category) }}</div>
            <div class="ledger-main">
              <p>{{ entry.content }}</p>
              <span>v{{ entry.version || 1 }} · {{ formatDate(entry.created_at) }}<template v-if="entry.source_run_id"> · run {{ entry.source_run_id.slice(0, 8) }}</template></span>
              <div v-if="historyById[entry.id]" class="memory-history">
                <span v-if="historyById[entry.id].loading">正在加载版本…</span>
                <ol v-else><li v-for="revision in historyById[entry.id].items" :key="revision.id"><b>v{{ revision.version }} · {{ revision.state }}</b><p>{{ revision.content }}</p><small>{{ formatDate(revision.created_at) }}</small></li></ol>
              </div>
            </div>
            <div class="ledger-actions"><button class="btn-text" @click="toggleHistory(entry)">{{ historyById[entry.id] ? '收起历史' : '历史' }}</button></div>
          </article>
        </template>
        <p v-else class="form-hint">每次保存都会为改动的条目留一个新版本，撤销的条目也保留在历史里。</p>
      </section>
    </template>
  </div>
</template>
