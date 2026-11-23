<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/backend.js'
import {
  cancelActiveRun,
  currentChatbot,
  hasStoppableRun,
  openSession,
  setInsightMode,
  showToast,
  store,
  syncComposerModeFromMessages,
} from '../store.js'
import { resumeLiveRun, sendQuestion } from '../chat.js'
import { conversationContext, tokenNumber } from '../context.js'
import ContextMeter from '../components/chat/ContextMeter.vue'
import AgentTrace from '../components/chat/AgentTrace.vue'
import ChatHome from '../components/chat/ChatHome.vue'
import ClarifyCard from '../components/chat/ClarifyCard.vue'
import AnswerCard from '../components/chat/AnswerCard.vue'
import DeferredContent from '../components/chat/DeferredContent.vue'
import WorkbookPanel from '../components/chat/WorkbookPanel.vue'
import { buildPreviewConversation } from '../data/agentCatalog.js'

const route = useRoute()
const previewMode = computed(() => false)
const previewMessages = reactive(buildPreviewConversation())
const displayMessages = computed(() => (previewMode.value ? previewMessages : store.messages))

const contextReading = computed(() => conversationContext(displayMessages.value))
const input = ref('')
const chatEl = ref(null)
const chatViewportHeight = ref(0)
let viewportObserver = null
const chatbot = computed(currentChatbot)
const xlsxMode = computed(() => Boolean(chatbot.value?.personal_uploads))
const workbookCount = computed(() => chatbot.value?.workbooks?.length || 0)
const filesOpen = ref(false)
const workbookUploading = ref(false)
const needsFiles = computed(() => xlsxMode.value && !workbookCount.value)
const insightMode = computed({
  get: () => store.insightMode,
  set: (value) => setInsightMode(value),
})
const skillModalOpen = ref(false)
const skillDraft = reactive({ customPrompt: '', skillPackId: '' })
const appliedSkill = store.insightSkill
const mountablePacks = ref([])
const skillLoaded = computed(() => Boolean(appliedSkill.customPrompt || appliedSkill.skillPackId))
const waitingForClarification = computed(() => store.messages.some(message => message.role === 'a' && message.status === 'waiting_clarification' && !message.clarify?.confirmed))
const historyBlocked = computed(() => {
  const latest = [...store.messages].reverse().find(message => message.role === 'a')
  return store.historyLoading || Boolean(store.historyError)
    || Boolean(latest?.historyLoading && !latest.answer?.md)
})
const modeLocked = computed(() => (
  store.busy
  || historyBlocked.value
  || waitingForClarification.value
  || hasStoppableRun()
  || workbookUploading.value
))
const canStop = computed(() => store.busy || hasStoppableRun())
const characterName = computed(() => xlsxMode.value ? 'XLSX 问数助手' : store.branding?.character_name || 'Gilead BI')
const logoUrl = computed(() => store.branding?.logo_url || '/brand/gilead-bi.svg')

const activeModelName = computed(() => store.models.find(model => model.is_active)?.name || '当前激活模型')
const modelMenuOpen = ref(false)
const thinkMenuOpen = ref(false)
const currentModelLabel = computed(() => {
  if (!store.modelChoice) return activeModelName.value
  return store.models.find(model => model.id === store.modelChoice)?.name || activeModelName.value
})
const thinkingLabel = computed(() => ({ default: '默认', on: '开', off: '关' }[store.thinking] || '默认'))
function pickModel(id) {
  store.modelChoice = id
  modelMenuOpen.value = false
}
const thinkingChoices = [
  { value: 'default', label: '默认' },
  { value: 'on', label: '开' },
  { value: 'off', label: '关' },
]
const thinkingLevels = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]

function focusQuestion() {
  if (previewMode.value) return
  const container = chatEl.value
  const id = store.focusMessageId || [...displayMessages.value].reverse().find(message => message.role === 'u')?.persistedId
  if (!id || !container) return
  const target = [...(container?.querySelectorAll('.turn-q') || [])].find(element => element.dataset.messageId === id)
  if (!target || !container) return
  container.scrollTop += target.getBoundingClientRect().top - container.getBoundingClientRect().top - 18
}

onMounted(() => {
  chatViewportHeight.value = chatEl.value?.clientHeight || 0
  viewportObserver = new ResizeObserver(() => {
    chatViewportHeight.value = chatEl.value?.clientHeight || 0
  })
  viewportObserver.observe(chatEl.value)
  if (!store.token && !previewMode.value) store.loginOpen = true
  // Route remounts ChatView; re-attach mode + live SSE so stop/mode lock work.
  syncComposerModeFromMessages()
  const live = [...store.messages].reverse().find(message => (
    message.role === 'a'
    && !message.historyLoading
    && message.runId
    && ['starting', 'accepted', 'received', 'running', 'resuming'].includes(message.status)
  ))
  if (live && !store.activeController && !previewMode.value) {
    resumeLiveRun(live)
  }
  nextTick(focusQuestion)
})
onBeforeUnmount(() => viewportObserver?.disconnect())

function send(text, reportContext = null) {
  if (previewMode.value) return
  const question = (text ?? input.value).trim()
  if (!question || store.busy || historyBlocked.value || waitingForClarification.value || workbookUploading.value) return
  if (needsFiles.value) { filesOpen.value = true; showToast('请先上传 XLSX 文件'); return }
  input.value = ''
  const insightOptions = {
    mode: 'normal',
    customPrompt: xlsxMode.value ? '' : appliedSkill.customPrompt || '',
    skillPackId: xlsxMode.value ? '' : appliedSkill.skillPackId || '',
  }
  const latestReport = [...store.messages].reverse().find(message => message.report)
  sendQuestion(question, insightOptions, reportContext || latestReport?.reportState || null)
}

async function openSkillModal() {
  if (modeLocked.value) return
  skillDraft.customPrompt = appliedSkill.customPrompt
  skillDraft.skillPackId = appliedSkill.skillPackId
  skillModalOpen.value = true
  try {
    const result = await api.mountableInsightSkillPacks()
    mountablePacks.value = result.items || []
  } catch (error) {
    showToast(error.message || '加载技能包失败')
  }
}

function clearSkillDraft() {
  skillDraft.customPrompt = ''
  skillDraft.skillPackId = ''
}

function applySkillModal() {
  appliedSkill.customPrompt = (skillDraft.customPrompt || '').trim()
  appliedSkill.skillPackId = skillDraft.skillPackId || ''
  const pack = mountablePacks.value.find(item => item.id === appliedSkill.skillPackId)
  appliedSkill.skillName = pack?.name || ''
  skillModalOpen.value = false
}

function clearAppliedSkill() {
  appliedSkill.customPrompt = ''
  appliedSkill.skillPackId = ''
  appliedSkill.skillName = ''
}

function setChatMode(mode) {
  if (modeLocked.value || previewMode.value) return
  insightMode.value = mode === 'insight'
}

watch(insightMode, (on) => {
  if (!on) {
    skillModalOpen.value = false
  }
})

function onEnter(event) {
  if (event.isComposing) return
  event.preventDefault()
  send()
}

watch(
  () => [store.sessionId, store.focusMessageId, store.historyLoading, store.focusRequest],
  async ([, id, loading]) => {
    if (!id || loading) return
    await nextTick()
    focusQuestion()
  },
)

async function retryHistory() {
  try { await openSession(store.sessionId) }
  catch (error) { showToast(error.message || '会话加载失败') }
}
</script>

<template>
  <div class="chat-shell">
  <main ref="chatEl" class="chat" :style="{ '--chat-viewport-height': `${chatViewportHeight}px` }">
    <section v-if="store.historyLoading && !previewMode" class="history-status" role="status"><i aria-hidden="true"></i><h2>正在打开历史对话…</h2><p>消息加载后会显示用户问题，图表与正文随后呈现。</p></section>
    <section v-else-if="store.historyError && !previewMode" class="history-status" role="alert"><h2>历史对话未能加载</h2><p>{{ store.historyError }}</p><button type="button" class="btn-p" @click="retryHistory">重新加载</button></section>
    <WorkbookPanel v-if="!store.historyLoading && !store.historyError && xlsxMode && !displayMessages.length && !filesOpen" :disabled="store.busy || waitingForClarification" @busy="workbookUploading = $event" />
    <ChatHome
      v-if="!store.historyLoading && !store.historyError && !displayMessages.length && !previewMode && !needsFiles"
      :character-name="characterName"
      :logo-url="logoUrl"
      :insight-mode="false"
      :disabled="modeLocked || store.busy || needsFiles"
      @ask="send"
    />
    <section v-else-if="!displayMessages.length && previewMode" class="hero">
      <div class="hero-face">
        <img class="hero-avatar" :src="logoUrl" :alt="characterName" />
        <span class="think-bubble" aria-hidden="true"><i></i><i></i><i></i></span>
      </div>
      <p class="hero-hi">嗨，我是{{ characterName }}</p>
      <h1>有问题先交给我，<br>我自己想一想。</h1>
      <p class="hero-sub">查数、对口径、核证据，都交给我。你只要问。</p>
    </section>
    <section v-else-if="displayMessages.length" class="cwrap">
      <template v-for="(message, index) in displayMessages" :key="message.persistedId || index">
        <article
          v-if="message.role === 'u'"
          class="turn-q"
          :class="{ focused: Boolean(message.persistedId) && store.focusMessageId === message.persistedId }"
          :data-message-id="message.persistedId || undefined"
          aria-label="你问"
        >
          <p class="turn-question">{{ message.text }}</p>
        </article>
        <article v-else class="turn-a">
          <p v-if="message.historyError" class="history-reply-error">{{ message.historyError }}</p>
          <DeferredContent :defer="Boolean(message.historical)" :pending="Boolean(message.historyLoading)" :min-height="340">
          <AgentTrace :msg="message" :agent-name="characterName" />
          <div v-for="notice in message.compactions" :key="notice.key" class="context-notice" role="status">
            <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path d="M4 7V3h4M16 13v4h-4M4 3l5 5m7 9-5-5M4 11v4a2 2 0 0 0 2 2h2m8-8V5a2 2 0 0 0-2-2h-2" />
            </svg>
            <span>上下文已自动压缩</span>
            <small>第 {{ notice.step }} 步 · {{ tokenNumber(notice.before) }} → {{ tokenNumber(notice.used) }} Token</small>
          </div>
          <ClarifyCard
            v-for="card in (message.clarifyHistory || [])"
            :key="`history-${card.caseId}`"
            :clarify="card"
            :msg="message"
          />
          <ClarifyCard
            v-if="message.clarify"
            :key="message.clarify.caseId || 'current'"
            :clarify="message.clarify"
            :msg="message"
          />
          <AnswerCard :msg="message" @ask="send" />
          </DeferredContent>
        </article>
      </template>
    </section>
  </main>
  <footer class="composer">
    <div class="cbox">
      <div v-if="!xlsxMode" class="ctools">
        <div class="tool-wrap">
          <button
            class="icon-btn"
            type="button"
            :class="{ picked: Boolean(store.modelChoice) }"
            :disabled="store.busy"
            :title="`模型：${currentModelLabel}`"
            @click="modelMenuOpen = !modelMenuOpen; thinkMenuOpen = false"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M5 8h9M18 8h1M5 12h3M12 12h7M5 16h11M20 16h-1" />
              <circle cx="16" cy="8" r="1.7" /><circle cx="10" cy="12" r="1.7" /><circle cx="18" cy="16" r="1.7" />
            </svg>
            <span class="btn-caret">▾</span>
          </button>
          <template v-if="modelMenuOpen">
            <div class="menu-veil" @click="modelMenuOpen = false"></div>
            <div class="model-menu">
              <button class="model-opt" :class="{ on: !store.modelChoice }" type="button" @click="pickModel('')">
                <span class="opt-main">跟随激活<em>{{ activeModelName }}</em></span>
                <span v-if="!store.modelChoice" class="opt-check">✓</span>
              </button>
              <button v-for="model in store.models" :key="model.id" class="model-opt" :class="{ on: store.modelChoice === model.id }" type="button" @click="pickModel(model.id)">
                <span class="opt-main">{{ model.name }}<em>{{ model.model_id }}<i v-if="model.is_active">激活</i></em></span>
                <span v-if="store.modelChoice === model.id" class="opt-check">✓</span>
              </button>
            </div>
          </template>
        </div>

        <div class="tool-wrap">
          <button
            class="icon-btn"
            type="button"
            :class="{ 'think-on': store.thinking === 'on', 'think-off': store.thinking === 'off' }"
            :disabled="store.busy"
            :title="`深度思考：${thinkingLabel}`"
            @click="thinkMenuOpen = !thinkMenuOpen; modelMenuOpen = false"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
              <path d="M12 3.5l1.9 5 5 1.9-5 1.9-1.9 5-1.9-5-5-1.9 5-1.9 1.9-5z" />
              <path d="M18.8 14.6l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9.9-2.3z" opacity=".75" />
              <path v-if="store.thinking === 'off'" d="M4.5 19.5L19.5 4.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none" />
            </svg>
            <span class="btn-caret">▾</span>
          </button>
          <template v-if="thinkMenuOpen">
            <div class="menu-veil" @click="thinkMenuOpen = false"></div>
            <div class="think-menu">
              <div class="mini-row">
                <span class="mini-eyebrow">思考</span>
                <button
                  v-for="choice in thinkingChoices"
                  :key="choice.value"
                  type="button"
                  :class="{ on: store.thinking === choice.value }"
                  :disabled="store.busy"
                  @click="store.thinking = choice.value"
                >{{ choice.label }}</button>
              </div>
              <div v-if="store.thinking === 'on'" class="mini-row">
                <span class="mini-eyebrow">强度</span>
                <button
                  v-for="level in thinkingLevels"
                  :key="level.value"
                  type="button"
                  :class="{ on: store.thinkingLevel === level.value }"
                  :disabled="store.busy"
                  @click="store.thinkingLevel = level.value"
                >{{ level.label }}</button>
              </div>
            </div>
          </template>
        </div>
      </div>
      <textarea
        v-model="input"
        rows="1"
        :placeholder="previewMode ? '样式预览中，不能发送' : historyBlocked ? '正在恢复历史对话…' : needsFiles ? '先上传 XLSX 文件，就可以开始问数' : workbookUploading ? '正在读取工作簿…' : waitingForClarification ? '请先完成上方口径确认' : store.busy ? '正在分析数据…' : xlsxMode ? '基于我的文件提问，例如：按区域汇总金额并生成柱状图' : '输入业务问题或继续追问…'"
        :disabled="previewMode || historyBlocked || store.busy || waitingForClarification || needsFiles || workbookUploading"
        @keydown.enter.exact="onEnter"
      ></textarea>
      <button v-if="canStop" class="stop" title="停止接收" @click="cancelActiveRun">■</button>
      <button v-else class="send" :disabled="previewMode || historyBlocked || !input.trim() || waitingForClarification || needsFiles || workbookUploading" @click="send()">↑</button>
    </div>
    <div v-if="skillLoaded && !xlsxMode" class="skill-chip-row">
      <span class="skill-chip">
        已加载{{ appliedSkill.skillName ? `「${appliedSkill.skillName}」` : '' }}{{ appliedSkill.customPrompt ? '自定义提示词' : '技能' }} · html模板
        <button type="button" class="chip-x" title="清除" @click="clearAppliedSkill">×</button>
      </span>
    </div>
    <div class="composer-meta">
      <ContextMeter :reading="contextReading" />
      <div class="composer-note"><span>{{ xlsxMode ? 'XLSX 问数' : characterName }}</span> · {{ xlsxMode ? '基于已上传文件回答 · 图表可加入我的看板' : '回答以运行事实为依据，重要决策请核验来源' }}</div>
    </div>
  </footer>
  <Teleport to="body"><WorkbookPanel v-if="xlsxMode && filesOpen" modal :disabled="store.busy || waitingForClarification" @close="filesOpen = false" @busy="workbookUploading = $event" /></Teleport>

  <div v-if="skillModalOpen" class="veil" @click.self="skillModalOpen = false">
    <div class="skill-modal" role="dialog" aria-modal="true" aria-label="加载技能模板">
      <header>
        <h2>加载技能模板</h2>
        <p>默认使用数据洞察主提示词；可追加自定义提示词，并选择分析技能；html模板自动应用到报告。</p>
      </header>
      <label class="field">
        <span>自定义提示词</span>
        <textarea v-model="skillDraft.customPrompt" rows="5" placeholder="例如：侧重区域达成与风险归因…" />
      </label>
      <div class="field">
        <span>数据洞察技能包</span>
        <div v-if="!mountablePacks.length" class="mini-empty">暂无可挂载技能包，请管理员在「技能包」页添加。</div>
        <div v-else class="pack-pick">
          <button
            type="button"
            class="pack-opt"
            :class="{ on: !skillDraft.skillPackId }"
            @click="skillDraft.skillPackId = ''"
          >不挂载</button>
          <button
            v-for="pack in mountablePacks"
            :key="pack.id"
            type="button"
            class="pack-opt"
            :class="{ on: skillDraft.skillPackId === pack.id }"
            @click="skillDraft.skillPackId = pack.id"
          >
            <b>{{ pack.name }}</b>
            <em>{{ pack.blurb || '数据洞察技能包' }}</em>
          </button>
        </div>
      </div>
      <footer>
        <button type="button" class="btn-g" @click="clearSkillDraft">清空</button>
        <button type="button" class="btn-g" @click="skillModalOpen = false">取消</button>
        <button type="button" class="btn-p" @click="applySkillModal">确认</button>
      </footer>
    </div>
  </div>
  </div>
</template>

<style scoped>
.files-toggle{display:flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--paper);color:var(--ink-2);border-radius:9px;cursor:pointer;padding:8px 11px;font-size:11px;margin-left:auto;margin-right:16px;white-space:nowrap}.files-toggle svg{height:17px;width:17px}.files-toggle b{font:10px var(--mono-font);color:var(--accent);margin-left:4px}.files-toggle:hover{border-color:var(--accent);color:var(--accent)}.files-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.files-toggle:disabled{opacity:.5;cursor:default}@media(max-width:700px){.files-toggle{font-size:10px;padding:7px 8px;margin-right:0}.chat-topbar>div>span{display:none}.connection-state{display:none}}
.preview-banner {
  background: #f7edda;
  border-bottom: 1px solid color-mix(in srgb, var(--warning) 35%, var(--line));
  color: var(--ink-2);
  font-size: 12px;
  padding: 8px 18px;
}
.mode-switch-wrap {
  display: flex;
  justify-content: center;
  padding: 10px 16px 4px;
  flex: 0 0 auto;
}
.mode-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border-radius: 999px;
  background: #efeff3;
  border: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 3px rgba(36, 38, 48, 0.02);
  backdrop-filter: blur(10px);
}
.mode-switch.locked {
  opacity: 0.72;
}
.mode-seg {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 0;
  background: transparent;
  color: #6b7c8f;
  cursor: pointer;
  border-radius: 999px;
  padding: 8px 16px;
  font: 600 13px/1 var(--body-font);
  letter-spacing: 0.01em;
  transition: color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}
.mode-seg:hover:not(:disabled):not(.on) {
  color: #3d5470;
}
.mode-seg.on {
  background: #fff;
  color: var(--accent);
  box-shadow: 0 4px 14px rgba(var(--accent-rgb), 0.08);
}
.mode-seg:disabled {
  cursor: default;
}
.mode-ico {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
}
/* compact icon toolbar, inline with the textarea */
.ctools { align-items: center; align-self: center; display: flex; gap: 4px; }
.tool-wrap { position: relative; }
.icon-btn {
  align-items: center; background: transparent; border: 1px solid transparent; border-radius: 9px;
  color: var(--ink-3); cursor: pointer; display: inline-flex; gap: 2px; height: 30px;
  justify-content: center; padding: 0 6px; transition: background .15s, color .15s;
}
.icon-btn:hover { background: var(--accent-soft); color: var(--accent); }
.icon-btn:disabled { cursor: default; opacity: .55; }
.icon-btn.picked, .icon-btn.think-on { background: var(--accent-soft); color: var(--accent); }
.icon-btn.think-off { color: var(--ink-3); opacity: .7; }
.btn-caret { font-size: 8px; transform: translateY(-1px); }
.menu-veil { inset: 0; position: fixed; z-index: 39; }

/* popovers open upward from the input row */
.model-menu, .think-menu {
  background: var(--paper); border: 1px solid var(--line); border-radius: 14px;
  bottom: calc(100% + 8px); box-shadow: var(--shadow-lg); left: 0;
  padding: 5px; position: absolute; z-index: 40;
}
.model-menu { min-width: 240px; }
.model-opt {
  align-items: center; background: transparent; border: 0; border-radius: 10px; cursor: pointer;
  display: flex; gap: 8px; padding: 7px 10px; text-align: left; width: 100%;
}
.model-opt:hover { background: var(--bg); }
.model-opt.on .opt-main { color: var(--accent); }
.opt-main { color: var(--ink); display: flex; flex-direction: column; font-size: 12.5px; font-weight: 650; gap: 1px; }
.opt-main em { color: var(--ink-3); font: 500 10px var(--mono-font); font-style: normal; }
.opt-main em i { background: var(--accent-soft); border-radius: 5px; color: var(--accent); font: 600 9px var(--mono-font); font-style: normal; margin-left: 6px; padding: 1px 5px; }
.opt-check { color: var(--accent); font-size: 12px; font-weight: 700; margin-left: auto; }

/* thinking mini menu */
.think-menu { display: flex; flex-direction: column; gap: 6px; min-width: 190px; padding: 9px 10px; }
.mini-row { align-items: center; display: flex; gap: 2px; }
.mini-eyebrow { color: var(--ink-3); flex: 0 0 34px; font: 600 9.5px var(--mono-font); letter-spacing: .08em; }
.mini-row button {
  background: transparent; border: 0; border-radius: var(--radius-pill); color: var(--ink-3);
  cursor: pointer; flex: 1 1 auto; font-size: 11.5px; font-weight: 650; height: 26px; transition: all .15s;
}
.mini-row button:hover { color: var(--accent); }
.mini-row button.on { background: var(--accent-soft); color: var(--accent); }
.mini-row button:disabled { cursor: default; opacity: .6; }

.skill-chip-row { margin-top: 6px; padding: 0 2px; }
.skill-chip {
  align-items: center; background: var(--accent-soft); border-radius: 999px; color: var(--accent-dark);
  display: inline-flex; font-size: 11.5px; font-weight: 650; gap: 6px; padding: 3px 8px 3px 10px;
}
.chip-x {
  background: transparent; border: 0; color: inherit; cursor: pointer; font-size: 14px; line-height: 1; padding: 0 2px;
}
.veil {
  align-items: center; background: rgba(12, 22, 18, .34); display: flex; inset: 0; justify-content: center;
  padding: 20px; position: fixed; z-index: 80;
}
.skill-modal {
  background: var(--paper); border-radius: 18px; box-shadow: var(--shadow-lg); display: grid; gap: 14px;
  max-height: min(86vh, 720px); overflow: auto; padding: 20px 22px 16px; width: min(520px, 100%);
}
.skill-modal h2 { font-size: 18px; margin: 0 0 4px; }
.skill-modal header p { color: var(--ink-3); font-size: 12.5px; line-height: 1.55; margin: 0; }
.field { display: grid; gap: 6px; }
.field > span { color: var(--ink-3); font-size: 11px; font-weight: 650; }
.field textarea {
  border: 1px solid var(--line); border-radius: 12px; font: 13px/1.5 var(--body-font);
  min-height: 110px; padding: 10px 12px; resize: vertical; width: 100%;
}
.pack-pick { display: grid; gap: 8px; }
.pack-opt {
  background: var(--bg); border: 1px solid var(--line); border-radius: 12px; cursor: pointer;
  display: grid; gap: 2px; padding: 10px 12px; text-align: left;
}
.pack-opt.on { border-color: var(--accent); background: var(--accent-soft); }
.pack-opt b { font-size: 13px; }
.pack-opt em { color: var(--ink-3); font-size: 12px; font-style: normal; }
.mini-empty { color: var(--ink-3); font-size: 12.5px; }
.skill-modal footer {
  border-top: 1px solid var(--line); display: flex; gap: 8px; justify-content: flex-end; padding-top: 12px;
}
</style>

<style scoped>
.template-loader{width:auto;min-width:72px;gap:5px;padding:4px 8px;font-size:11px;white-space:nowrap}.template-loader span{max-width:90px;overflow:hidden;text-overflow:ellipsis}@media(max-width:700px){.template-loader{min-width:65px;padding:4px}.template-loader span{max-width:66px}}
</style>
