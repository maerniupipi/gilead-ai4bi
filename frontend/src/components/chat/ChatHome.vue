<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../api/backend.js'
import { homeExamplesForChatbot } from '../../data/homeExamples.js'
import { currentChatbot, openSession, showToast, store } from '../../store.js'

const props = defineProps({
  characterName: { type: String, default: 'Gilead BI' },
  logoUrl: { type: String, required: true },
  insightMode: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['ask'])

const loadingHistory = ref(false)
const recent = ref([])
const popular = ref([])

const chatbot = computed(currentChatbot)
const examples = computed(() => homeExamplesForChatbot(chatbot.value, props.insightMode))
const modeHint = computed(() => (
  chatbot.value?.category === 'behavior' ? '围绕访问、活跃、转化与复访，理解用户路径，发现增长机会' :
  props.insightMode
    ? '从指标变化出发，主动下钻区域、渠道和机构，发现增长驱动'
    : '用自然语言查询销售表现、目标达成与同环比，数据依据可追溯'
))

function normalizeQuestion(text) {
  return String(text || '')
    .trim()
    .replace(/\s+/g, '')
    .toLowerCase()
}

function formatShortDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

function buildRecent(items) {
  const seen = new Set()
  const rows = []
  for (const item of items) {
    const text = String(item.content || '').trim()
    if (!text) continue
    const key = normalizeQuestion(text)
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({
      id: item.id,
      sessionId: item.session_id,
      text,
      meta: formatShortDate(item.created_at),
    })
    if (rows.length >= 3) break
  }
  return rows
}

function buildPopular(items) {
  const map = new Map()
  for (const item of items) {
    const text = String(item.content || '').trim()
    if (!text) continue
    const key = normalizeQuestion(text)
    const prev = map.get(key)
    if (!prev) {
      map.set(key, { text, count: 1, at: item.created_at, messageId: item.id, sessionId: item.session_id })
      continue
    }
    prev.count += 1
    if (String(item.created_at || '') > String(prev.at || '')) {
      prev.at = item.created_at
      prev.text = text
      prev.messageId = item.id
      prev.sessionId = item.session_id
    }
  }
  return [...map.values()]
    .sort((a, b) => b.count - a.count || String(b.at).localeCompare(String(a.at)))
    .slice(0, 3)
    .map((row, index) => ({
      id: `pop-${index}-${row.count}`,
      messageId: row.messageId,
      sessionId: row.sessionId,
      text: row.text,
      meta: `${row.count} 次`,
    }))
}

async function loadHistory() {
  if (!store.token) {
    recent.value = []
    popular.value = []
    return
  }
  loadingHistory.value = true
  try {
    const page = await api.chatQuestions({ limit: 100, offset: 0, chatbot_id: store.chatbotId })
    const items = Array.isArray(page?.items) ? page.items : []
    recent.value = buildRecent(items)
    popular.value = buildPopular(items)
  } catch {
    recent.value = []
    popular.value = []
  } finally {
    loadingHistory.value = false
  }
}

function ask(text) {
  const question = String(text || '').trim()
  if (!question || props.disabled) return
  emit('ask', question)
}

async function viewHistory(item) {
  if (props.disabled) return
  if (!item.sessionId) { ask(item.text); return }
  try { await openSession(item.sessionId, { focusMessageId: item.messageId || item.id }) }
  catch (error) { showToast(error.message || '对话加载失败，请稍后重试') }
}

onMounted(loadHistory)
watch(
  () => store.token,
  () => { void loadHistory() },
)
watch(
  () => store.messages.length,
  (len, prev) => {
    // Refresh after a conversation is cleared / new chat starts.
    if (len === 0 && prev > 0) void loadHistory()
  },
)
</script>

<template>
  <section class="chat-home" aria-label="首页示例">
    <header v-if="!chatbot?.personal_uploads" class="home-hero">
      <div class="enterprise-kicker">GILEAD · BUSINESS INTELLIGENCE</div>
      <div class="home-chatbot-label">{{ chatbot?.name || '业务对话' }}<small>{{ chatbot?.lab_ids?.length ? '实验室数据' : 'XLSX 工作簿' }}<template v-if="chatbot?.sample"> · 样例数据</template></small></div>
      <div class="enterprise-hero-title"><img class="hero-avatar" :src="logoUrl" :alt="characterName" /><h1>{{ chatbot?.category === 'behavior' ? (insightMode ? '理解行为变化，找到增长机会' : '看清用户行为，让增长有迹可循') : (insightMode ? '洞察商业表现，明确行动方向' : '让每个业务问题，都有数据依据') }}</h1></div>
      <p class="hero-sub">{{ modeHint }}</p>
    </header>

    <div class="example-grid" aria-label="推荐问题">
      <article v-for="group in examples" :key="group.id" class="example-card">
        <div class="example-head">
          <span class="example-ico" :data-icon="group.icon" aria-hidden="true"></span>
          <b>{{ group.title }}</b>
        </div>
        <button
          v-for="(question, index) in group.questions"
          :key="`${group.id}-${index}`"
          type="button"
          class="example-q"
          :disabled="disabled"
          @click="ask(question)"
        >
          <span>{{ question }}</span>
          <i aria-hidden="true">↗</i>
        </button>
      </article>
    </div>

    <div class="home-boards">
      <section class="home-board" aria-label="最近问过">
        <header class="board-head">
          <div>
            <strong>最近问过</strong>
            <em>TOP 3</em>
          </div>
          <span>按提问时间</span>
        </header>
        <ol v-if="recent.length" class="board-list">
          <li v-for="(item, index) in recent" :key="item.id">
            <button type="button" class="board-item" title="查看原对话与回答" :disabled="disabled" @click="viewHistory(item)">
              <span class="rank">{{ index + 1 }}</span>
              <span class="qtext">{{ item.text }}</span>
              <span class="meta">{{ item.meta }}</span>
              <i aria-hidden="true">↗</i>
            </button>
          </li>
        </ol>
        <p v-else class="board-empty">
          {{ loadingHistory ? '加载中…' : (store.token ? '还没有提问记录' : '登录后可查看最近提问') }}
        </p>
      </section>

      <section class="home-board" aria-label="问得最多">
        <header class="board-head">
          <div>
            <strong>问得最多</strong>
            <em>TOP 3</em>
          </div>
          <span>按累计次数</span>
        </header>
        <ol v-if="popular.length" class="board-list">
          <li v-for="(item, index) in popular" :key="item.id">
            <button type="button" class="board-item" title="查看原对话与回答" :disabled="disabled" @click="viewHistory(item)">
              <span class="rank">{{ index + 1 }}</span>
              <span class="qtext">{{ item.text }}</span>
              <span class="meta">{{ item.meta }}</span>
              <i aria-hidden="true">↗</i>
            </button>
          </li>
        </ol>
        <p v-else class="board-empty">
          {{ loadingHistory ? '加载中…' : (store.token ? '提问几次后会在这里汇总' : '登录后可查看高频问题') }}
        </p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.home-chatbot-label{display:flex;align-items:center;gap:12px;font-size:11px;font-weight:600;color:#9f4055;margin-bottom:14px}.home-chatbot-label small{font-size:8px;font-weight:400;color:#ac9da6;border-left:1px solid #e7dce1;padding-left:12px}
.chat-home {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin: 0 auto;
  max-width: 920px;
  padding: 18px 28px 28px;
  width: 100%;
}
.chat-home *,
.chat-home *::before,
.chat-home *::after {
  box-sizing: border-box;
}
.home-hero {
  align-items: flex-start;
  display: flex;
  flex-direction: column;
  text-align: left;
  padding: 28px 0 10px;
}
.hero-face {
  height: 88px;
  margin-bottom: 12px;
  position: relative;
  width: 88px;
}
.hero-avatar {
  border-radius: 50%;
  box-shadow: 0 12px 28px rgba(var(--accent-rgb), 0.16);
  height: 88px;
  object-fit: cover;
  width: 88px;
}
.think-bubble {
  align-items: center;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(43, 22, 34, 0.1);
  display: flex;
  gap: 3px;
  padding: 6px 8px;
  position: absolute;
  right: -8px;
  top: 4px;
}
.think-bubble i {
  animation: think-dot 1.2s ease-in-out infinite;
  background: var(--accent);
  border-radius: 50%;
  display: block;
  height: 4px;
  width: 4px;
}
.think-bubble i:nth-child(2) { animation-delay: 0.15s; }
.think-bubble i:nth-child(3) { animation-delay: 0.3s; }
@keyframes think-dot {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}
.hero-hi {
  color: var(--accent);
  font-size: 13px;
  font-weight: 650;
  margin: 0 0 4px;
}
.home-hero h1 {
  font-family: var(--display-font);
  font-size: clamp(24px, 3.4vw, 32px);
  font-weight: 650;
  letter-spacing: -0.03em;
  line-height: 1.2;
  margin: 0;
}
.hero-sub {
  color: var(--ink-3);
  font-size: 13px;
  line-height: 1.55;
  margin: 8px 0 0;
  max-width: 420px;
}

.example-grid {
  align-items: stretch;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
}
.example-card {
  background: color-mix(in srgb, #fff 88%, var(--accent-soft));
  border: 1px solid color-mix(in srgb, var(--accent) 14%, var(--line));
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  height: 168px;
  min-width: 0;
  overflow: hidden;
  padding: 12px 12px 10px;
  width: 100%;
}
.example-head {
  align-items: center;
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  padding: 0 2px 4px;
}
.example-head b {
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
}
.example-ico {
  background: color-mix(in srgb, var(--accent) 14%, #fff);
  border-radius: 9px;
  color: var(--accent);
  display: inline-grid;
  height: 28px;
  place-items: center;
  width: 28px;
}
.example-ico::before {
  content: '';
  display: block;
  height: 14px;
  width: 14px;
  background: currentColor;
  mask-repeat: no-repeat;
  mask-position: center;
  mask-size: contain;
}
.example-ico[data-icon='chart']::before {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect x='2' y='8' width='3' height='6' rx='1' fill='black'/%3E%3Crect x='6.5' y='4' width='3' height='10' rx='1' fill='black'/%3E%3Crect x='11' y='6' width='3' height='8' rx='1' fill='black'/%3E%3C/svg%3E");
}
.example-ico[data-icon='target']::before {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='5.5' fill='none' stroke='black' stroke-width='1.6'/%3E%3Ccircle cx='8' cy='8' r='2.2' fill='black'/%3E%3C/svg%3E");
}
.example-ico[data-icon='rank']::before {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3 12h3V8H3v4zm5 0h3V4H8v8zm5 0h3V6h-3v6z' fill='black'/%3E%3C/svg%3E");
}
.example-q {
  align-items: start;
  background: transparent;
  border: 0;
  border-radius: 10px;
  color: var(--ink-2);
  cursor: pointer;
  display: grid;
  flex: 1 1 auto;
  font: 500 12.5px/1.45 var(--body-font);
  gap: 8px;
  grid-template-columns: minmax(0, 1fr) auto;
  min-height: 3.1em;
  padding: 8px 6px;
  text-align: left;
  width: 100%;
}
.example-q > span {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.example-q:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.72);
  color: var(--ink);
}
.example-q:disabled { cursor: default; opacity: 0.55; }
.example-q i {
  color: var(--accent);
  font-style: normal;
  opacity: 0.55;
  padding-top: 1px;
}
.example-q:hover:not(:disabled) i { opacity: 1; }

.home-boards {
  align-items: stretch;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
}
.home-board {
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--line);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  height: 214px;
  margin: 0;
  max-width: none;
  min-width: 0;
  overflow: hidden;
  padding: 12px 12px 8px;
  width: 100%;
}
.board-head {
  align-items: baseline;
  display: flex;
  flex: 0 0 auto;
  justify-content: space-between;
  margin-bottom: 6px;
  padding: 0 4px 4px;
}
.board-head > div {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}
.board-head strong {
  font-size: 13.5px;
  font-weight: 700;
}
.board-head em {
  background: color-mix(in srgb, var(--accent) 12%, #fff);
  border-radius: 999px;
  color: var(--accent);
  font: 700 10px/1 var(--mono-font);
  font-style: normal;
  padding: 3px 7px;
}
.board-head > span {
  color: var(--ink-3);
  flex: 0 0 auto;
  font-size: 11px;
}
.board-list {
  display: grid;
  flex: 1 1 auto;
  gap: 2px;
  grid-template-rows: repeat(3, minmax(0, 1fr));
  list-style: none;
  margin: 0;
  min-height: 0;
  padding: 0;
}
.board-list > li {
  min-height: 0;
  min-width: 0;
}
.board-item {
  align-items: start;
  background: transparent;
  border: 0;
  border-radius: 10px;
  cursor: pointer;
  display: grid;
  gap: 8px;
  grid-template-columns: 18px minmax(0, 1fr) auto auto;
  height: 100%;
  padding: 8px 6px;
  text-align: left;
  width: 100%;
}
.board-item:hover:not(:disabled) {
  background: color-mix(in srgb, var(--accent-soft) 55%, #fff);
}
.board-item:disabled { cursor: default; opacity: 0.55; }
.rank {
  color: var(--accent);
  font: 700 12px/1.4 var(--mono-font);
  padding-top: 1px;
}
.qtext {
  color: var(--ink);
  display: -webkit-box;
  font-size: 12.5px;
  line-height: 1.45;
  min-width: 0;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.meta {
  color: var(--ink-3);
  font-size: 11px;
  padding-top: 2px;
  white-space: nowrap;
}
.board-item i {
  color: var(--accent);
  font-style: normal;
  opacity: 0.45;
  padding-top: 1px;
}
.board-item:hover:not(:disabled) i { opacity: 1; }
.board-empty {
  color: var(--ink-3);
  flex: 1 1 auto;
  font-size: 12.5px;
  margin: 0;
  padding: 14px 6px 12px;
}

@media (max-width: 860px) {
  .chat-home { padding: 14px 16px 22px; }
  .example-grid,
  .home-boards {
    grid-template-columns: minmax(0, 1fr);
  }
  .example-card,
  .home-board {
    height: auto;
    min-height: 148px;
  }
}
</style>

<style scoped>
.enterprise-kicker{display:inline-flex;align-items:center;gap:8px;font-size:10px;font-weight:600;letter-spacing:1.8px;color:var(--accent);margin-bottom:24px;background:var(--accent-soft);padding:5px 11px;border-radius:20px}
.enterprise-kicker:before{content:'';width:5px;height:5px;border-radius:50%;background:var(--accent)}
.enterprise-hero-title{display:flex;align-items:center;gap:16px}
.enterprise-hero-title .hero-avatar{display:none}
.enterprise-hero-title h1{font-size:clamp(24px,2.6vw,34px);letter-spacing:-1.4px;font-weight:650;line-height:1.45;color:var(--ink)}
.home-hero .hero-sub{font-size:13px;color:var(--ink-2);margin:14px 0 0;max-width:620px;line-height:1.8}
.home-hero{padding:28px 0 18px}
.chat-home{max-width:1100px;padding:26px 44px 32px;gap:25px}
.example-card{border-radius:20px;background:#fff;border:1px solid #e8e8ef;box-shadow:0 3px 10px #24263003;padding:20px 18px;transition:transform .22s,box-shadow .22s,border-color .22s}
.example-card:hover{border-color:#c5203f24;box-shadow:0 12px 28px #24263007;transform:translateY(-3px)}
.example-head{margin-bottom:12px;gap:10px}.example-head b{font-size:14px;font-weight:600;letter-spacing:-.2px}.example-ico{color:var(--accent);background:#fbedf0;border-radius:11px;width:34px;height:34px}
.example-q{font-size:12px;line-height:1.65;padding:10px 0;border-radius:0;border-bottom:1px solid #f0f0f4}.example-q:last-child{border-bottom:0}.example-q:hover:not(:disabled){background:transparent;color:var(--accent)}
.home-board{background:transparent;border:0;padding:8px 0}.board-head{border-bottom:1px solid #e9e9ef;padding:0 4px 12px}.board-head strong{font-size:13px}.board-head em{background:#efeff3;color:#8c8c97;border-radius:5px;font-size:8px;letter-spacing:.4px}
.board-item{padding:11px 5px}.qtext{font-size:12px;color:var(--ink-2)}.rank{color:#a2a2ad;font-weight:500}.board-empty{font-size:12px;padding-top:22px}
@media(max-width:1000px){.chat-home{padding:20px 28px}.example-grid{gap:10px}.example-card{padding:16px}}
@media(max-width:700px){.enterprise-hero-title h1{font-size:24px;letter-spacing:-.7px}.chat-home{padding:14px 18px}.home-hero{padding-top:15px}.enterprise-kicker{font-size:8px;margin-bottom:18px}.example-card:hover{transform:none}}
@media(prefers-reduced-motion:reduce){.example-card{transition:none}.example-card:hover{transform:none}}
</style>
