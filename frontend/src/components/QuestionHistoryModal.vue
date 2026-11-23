<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/backend.js'
import { formatDate, openSession, showToast, store } from '../store.js'

const PAGE_SIZE = 20
const emit = defineEmits(['close'])
const router = useRouter()
const items = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const listEl = ref(null)
let requestSeq = 0

const pageCount = computed(() => Math.max(1, Math.ceil((total.value || 0) / PAGE_SIZE)))
const rangeText = computed(() => {
  if (!total.value) return '还没有提问记录'
  const start = (page.value - 1) * PAGE_SIZE + 1
  const end = Math.min(page.value * PAGE_SIZE, total.value)
  return `第 ${start}–${end} 条，共 ${total.value} 个问题`
})

async function load(nextPage = page.value) {
  const seq = ++requestSeq
  loading.value = true
  try {
    const result = await api.chatQuestions({
      limit: PAGE_SIZE,
      offset: (nextPage - 1) * PAGE_SIZE,
      chatbot_id: store.chatbotId,
    })
    if (seq !== requestSeq) return
    items.value = result.items || []
    total.value = result.total || 0
    page.value = nextPage
    if (listEl.value) listEl.value.scrollTop = 0
  } catch (error) {
    if (seq !== requestSeq) return
    showToast('历史问题加载失败：' + error.message)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function go(delta) {
  const next = page.value + delta
  if (next < 1 || next > pageCount.value || loading.value) return
  load(next)
}

function sessionHint(item) {
  const title = (item.session_title || '').trim()
  const content = (item.content || '').trim()
  if (!title) return ''
  if (content.startsWith(title) || title.startsWith(content.slice(0, Math.min(content.length, title.length)))) return ''
  return title
}

async function openQuestion(item) {
  emit('close')
  try {
    const alreadyOpen = store.sessionId === item.session_id
      && store.messages.some(message => message.persistedId === item.id)
    if (alreadyOpen) {
      store.focusMessageId = item.id
      store.focusRequest += 1
      await router.push('/')
    } else {
      await Promise.all([openSession(item.session_id, { focusMessageId: item.id }), router.push('/')])
    }
  } catch (error) {
    showToast('会话加载失败：' + error.message)
  }
}

function onKey(event) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  load(1)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="veil" @click.self="emit('close')">
    <div class="history-modal" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <header class="history-head">
        <div>
          <span>最近会话</span>
          <h2 id="history-title">全部提问</h2>
        </div>
        <button class="history-close" type="button" aria-label="关闭" @click="emit('close')">关闭</button>
      </header>
      <p class="history-copy">{{ loading && !items.length ? '正在加载…' : rangeText }}</p>
      <div ref="listEl" class="history-list">
        <p v-if="!loading && !items.length" class="history-empty">还没有提问记录</p>
        <button
          v-for="item in items"
          :key="item.id"
          class="history-item"
          :class="{ on: store.focusMessageId === item.id }"
          type="button"
          @click="openQuestion(item)"
        >
          <span class="history-question">{{ item.content }}</span>
          <span class="history-meta">
            <span v-if="sessionHint(item)" class="history-session">{{ sessionHint(item) }}</span>
            <time>{{ formatDate(item.created_at) }}</time>
          </span>
        </button>
      </div>
      <footer v-if="total > PAGE_SIZE" class="history-pager">
        <button type="button" class="btn-g" :disabled="loading || page <= 1" @click="go(-1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button type="button" class="btn-g" :disabled="loading || page >= pageCount" @click="go(1)">下一页</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.history-modal {
  background: var(--paper);
  border-radius: 22px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  max-height: min(86vh, 720px);
  padding: 22px 22px 16px;
  text-align: left;
  width: min(520px, 100%);
}
.history-head {
  align-items: flex-start;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}
.history-head span {
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
}
.history-head h2 {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -.02em;
  margin-top: 2px;
}
.history-close {
  background: transparent;
  border: 0;
  border-radius: 10px;
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 650;
  padding: 6px 8px;
}
.history-close:hover { background: var(--accent-soft); color: var(--accent); }
.history-copy {
  color: var(--ink-2);
  font-size: 12.5px;
  margin: 8px 0 14px;
}
.history-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}
.history-empty {
  color: var(--ink-3);
  font-size: 13px;
  padding: 36px 8px;
  text-align: center;
}
.history-item {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  text-align: left;
  width: 100%;
}
.history-item:hover {
  background: rgba(var(--accent-rgb), .05);
  border-color: var(--line);
}
.history-item.on {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 28%, var(--line));
}
.history-question {
  color: var(--ink);
  display: -webkit-box;
  font-size: 13.5px;
  font-weight: 550;
  letter-spacing: -.01em;
  line-height: 1.45;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
}
.history-meta {
  align-items: center;
  color: var(--ink-3);
  display: flex;
  font-size: 11px;
  gap: 8px;
}
.history-session {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-pager {
  align-items: center;
  border-top: 1px solid var(--line);
  display: flex;
  gap: 10px;
  justify-content: space-between;
  margin-top: 14px;
  padding-top: 12px;
}
.history-pager span {
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
}
.history-pager .btn-g {
  min-height: 32px;
  padding: 5px 12px;
}
</style>
