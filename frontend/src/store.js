import { reactive, watch } from 'vue'
import { api, onUnauthorized, setAccessToken } from './api/backend.js'
import { DEFAULT_BRANDING, applyBrandingToDocument, mergeBranding } from './branding.js'
import { yieldToBrowser } from './utils/rendering.js'

const LS_KEY = 'xiaoying.quick.session.v1'

function readSaved() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {} } catch { return {} }
}

const saved = readSaved()
let authEpoch = 0
let sessionRequestSeq = 0
let historyController = null
let authNavigationHandler = null

function persistSession(value) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(value)) } catch { /* quota/private mode */ }
}

const LIVE_RUN_STATUSES = new Set([
  'starting', 'accepted', 'received', 'running', 'resuming', 'waiting_clarification',
])

export const store = reactive({
  token: saved.token || '',
  expiresAt: saved.expiresAt || '',
  user: saved.user || null,
  authReady: false,
  loginOpen: false,
  chatbotId: saved.chatbotId || '',
  chatbots: [],
  chatbotChooserOpen: !saved.token || !saved.chatbotId,
  pendingChatbotId: '',
  chatbotLoading: false,
  chatbotError: '',
  sessionId: saved.sessionId || '',
  sessions: [],
  messages: [],
  focusMessageId: '',
  focusRequest: 0,
  historyLoading: false,
  historyError: '',
  busy: false,
  streamState: 'idle',
  activeController: null,
  liveSessions: {},
  reviewPending: 0,
  toast: '',
  // Composer model/thinking choices ('' = active default model, 'default' =
  // keep the model's configured thinking behaviour).
  models: [],
  modelChoice: saved.modelChoice || '',
  thinking: saved.thinking || 'default',
  thinkingLevel: saved.thinkingLevel || 'medium',
  // Chat composer mode survives route changes (e.g. 对话 ↔ 运行轨迹).
  insightMode: false,
  insightSkill: {
    customPrompt: String(saved.insightSkill?.customPrompt || ''),
    skillPackId: String(saved.insightSkill?.skillPackId || ''),
    skillName: String(saved.insightSkill?.skillName || ''),
  },
  branding: { ...DEFAULT_BRANDING },
})

export function setAuthNavigationHandler(handler) {
  authNavigationHandler = handler
}

setAccessToken(store.token)
onUnauthorized(() => {
  clearAuth()
  store.loginOpen = true
  showToast('会话已失效，请重新登录')
})

watch(
  () => ({
    token: store.token,
    expiresAt: store.expiresAt,
    user: store.user,
    sessionId: store.sessionId,
    chatbotId: store.chatbotId,
    modelChoice: store.modelChoice,
    thinking: store.thinking,
    thinkingLevel: store.thinkingLevel,
    insightMode: store.insightMode,
    insightSkill: store.insightSkill,
  }),
  persistSession,
  { deep: true },
)

let toastTimer = null
export function showToast(text, ms = 2800) {
  store.toast = text
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { store.toast = '' }, ms)
}

function clearAuth(abort = true) {
  authEpoch += 1
  sessionRequestSeq += 1
  historyController?.abort()
  historyController = null
  store.historyLoading = false
  store.historyError = ''
  if (abort) store.activeController?.abort()
  store.token = ''
  store.expiresAt = ''
  store.user = null
  store.chatbotId = ''
  store.pendingChatbotId = ''
  store.chatbotChooserOpen = true
  store.chatbots = []
  store.sessionId = ''
  store.sessions = []
  store.messages = []
  store.focusMessageId = ''
  store.reviewPending = 0
  store.busy = false
  store.streamState = 'idle'
  store.activeController = null
  store.liveSessions = {}
  setAccessToken('')
  try { localStorage.removeItem(LS_KEY) } catch { /* private mode */ }
  authNavigationHandler?.()
}

export async function restoreSession() {
  if (!store.token) {
    await loadChatbots()
    store.authReady = true
    return false
  }
  if (store.expiresAt && Date.parse(store.expiresAt) <= Date.now()) {
    clearAuth()
    await loadChatbots()
    store.authReady = true
    return false
  }
  try {
    setAccessToken(store.token)
    store.user = await api.me()
    await loadChatbots()
    await Promise.allSettled([loadSessions(), loadReviewCount(), loadModels()])
    if (store.sessionId) {
      const savedSessionId = store.sessionId
      if (store.sessions.some(session => session.id === savedSessionId)) {
        try { await openSession(savedSessionId) }
        catch { store.sessionId = ''; store.messages = []; store.focusMessageId = '' }
      } else {
        store.sessionId = ''
        store.messages = []
        store.focusMessageId = ''
      }
    }
    return true
  } catch {
    clearAuth()
    await loadChatbots()
    return false
  } finally {
    store.authReady = true
  }
}

export async function login(username, password) {
  const pendingChatbotId = store.pendingChatbotId
  let selectionDenied = false
  const result = await api.login(username.trim(), password)
  authEpoch += 1
  sessionRequestSeq += 1
  historyController?.abort()
  historyController = null
  store.historyLoading = false
  store.historyError = ''
  store.activeController?.abort()
  store.activeController = null
  store.busy = false
  store.streamState = 'idle'
  store.token = result.access_token
  store.expiresAt = result.expires_at || ''
  store.user = result.user
  store.sessionId = ''
  store.messages = []
  store.focusMessageId = ''
  store.liveSessions = {}
  setAccessToken(store.token)
  persistSession({ token: store.token, expiresAt: store.expiresAt, user: store.user, sessionId: store.sessionId })
  store.loginOpen = false
  await loadChatbots()
  const selectedId = pendingChatbotId || store.chatbots.find(bot => bot.id === 'ddi')?.id || store.chatbots[0]?.id || ''
  if (selectedId && store.chatbots.some(bot => bot.id === selectedId)) {
    await chooseChatbot(selectedId)
  } else {
    store.chatbotId = ''
    store.chatbotChooserOpen = true
    selectionDenied = Boolean(pendingChatbotId)
  }
  authNavigationHandler?.()
  await Promise.allSettled([loadSessions(), loadReviewCount(), loadModels()])
  showToast(selectionDenied ? '当前账号没有该助手的使用权，请选择可用 Chatbot'
    : `欢迎回来，${store.user.display_name || store.user.username}`)
  return store.user
}

export function logout() {
  clearAuth()
  store.loginOpen = false
  void loadChatbots()
}

export function currentChatbot() {
  return store.chatbots.find(bot => bot.id === store.chatbotId) || null
}

export async function loadChatbots() {
  const epoch = authEpoch
  const authenticated = Boolean(store.token)
  store.chatbotLoading = true
  store.chatbotError = ''
  try {
    const bots = authenticated ? await api.chatbots() : await api.chatbotEntrances()
    if (epoch !== authEpoch) return
    store.chatbots = bots
    if (authenticated && !store.chatbotId && bots.length && !store.pendingChatbotId) {
      store.chatbotId = (bots.find(bot=>bot.id==='ddi') || bots[0]).id
      store.chatbotChooserOpen = false
    }
    if (bots.length === 1 && bots[0].personal_uploads) {
      if (store.chatbotId !== bots[0].id) {
        newChat()
        store.sessions = []
      }
      store.chatbotId = bots[0].id
      store.chatbotChooserOpen = false
      if (!authenticated) store.pendingChatbotId = bots[0].id
    }
    if (authenticated && store.chatbotId && !bots.some(bot => bot.id === store.chatbotId)) {
      newChat()
      store.chatbotId = ''
      store.sessions = []
      store.chatbotChooserOpen = true
    }
  } catch (error) {
    if (epoch === authEpoch) store.chatbotError = error.message || '助手加载失败'
  } finally {
    if (epoch === authEpoch) store.chatbotLoading = false
  }
}

export async function chooseChatbot(id) {
  if (!store.token) {
    store.pendingChatbotId = id
    store.loginOpen = true
    return false
  }
  if (!store.chatbots.some(bot => bot.id === id)) throw new Error('当前账号没有该助手的使用权')
  newChat()
  store.chatbotId = id
  store.sessions = []
  store.insightMode = false
  Object.assign(store.insightSkill, { customPrompt: '', skillPackId: '', skillName: '' })
  store.chatbotChooserOpen = false
  store.pendingChatbotId = ''
  await loadSessions()
  return true
}

export function openChatbotChooser() {
  store.chatbotChooserOpen = true
  store.loginOpen = false
  void loadChatbots()
}

export function isSessionLive(sessionId) {
  const live = store.liveSessions[sessionId]
  return Boolean(live && LIVE_RUN_STATUSES.has(live.status))
}

export function hasStoppableRun() {
  return store.messages.some(message => (
    message.role === 'a'
    && LIVE_RUN_STATUSES.has(message.status)
    && message.status !== 'waiting_clarification'
  ))
}

export function syncComposerModeFromMessages() {
  // Only pin composer mode while a run is still live — otherwise keep the
  // user's persisted toggle (so finishing an insight turn does not trap them).
  const live = [...store.messages].reverse().find(message => (
    message.role === 'a' && LIVE_RUN_STATUSES.has(message.status)
  ))
  if (!live) return
  store.insightMode = Boolean(live.modelOptions?.mode === 'insight')
}

export function setInsightMode(on) {
  store.insightMode = Boolean(on)
}

export function markLiveSession(sessionId, message) {
  if (!sessionId || !message?.runId) return
  if (!LIVE_RUN_STATUSES.has(message.status)) {
    delete store.liveSessions[sessionId]
    return
  }
  store.liveSessions[sessionId] = { runId: message.runId, status: message.status }
}

function detachCurrentStream() {
  const sessionId = store.sessionId
  const message = [...store.messages].reverse().find(item => item.role === 'a' && item.runId)
  if (sessionId && message) markLiveSession(sessionId, message)
  store.activeController?.abort()
  store.activeController = null
}

export function newChat() {
  sessionRequestSeq += 1
  historyController?.abort()
  historyController = null
  store.historyLoading = false
  store.historyError = ''
  detachCurrentStream()
  store.busy = false
  store.streamState = 'idle'
  store.sessionId = ''
  store.messages = []
  store.focusMessageId = ''
}

export async function cancelActiveRun() {
  const message = [...store.messages].reverse().find(item => item.role === 'a' && !['completed', 'partial', 'failed', 'cancelled', 'done', 'client_cancelled'].includes(item.status))
  const runId = message?.runId || ''
  store.activeController?.abort()
  store.activeController = null
  store.busy = false
  store.streamState = 'cancelled'
  if (message) {
    message.status = 'client_cancelled'
    if (message.thinking) message.thinking.streaming = false
    if (message.answer) message.answer.done = true
  }
  if (runId && store.token) {
    try {
      await api.cancelRun(runId)
      showToast('已停止')
    } catch (error) {
      showToast(error?.message || '已停止接收；服务端取消未成功')
    }
    return
  }
  showToast('已停止')
}

export async function loadSessions() {
  if (!store.token || !store.chatbotId) return
  const epoch = authEpoch
  const chatbotId = store.chatbotId
  const sessions = await api.chatSessions({ chatbot_id: chatbotId })
  if (epoch === authEpoch && chatbotId === store.chatbotId) store.sessions = sessions
}

export async function loadBranding() {
  try {
    const payload = await api.branding()
    store.branding = mergeBranding(payload)
  } catch {
    store.branding = mergeBranding(DEFAULT_BRANDING)
  }
  applyBrandingToDocument(store.branding)
  return store.branding
}

export async function loadModels() {
  if (!store.token) return
  const epoch = authEpoch
  try {
    const models = await api.chatModels()
    if (epoch !== authEpoch) return
    store.models = models
    if (store.modelChoice && !models.some(model => model.id === store.modelChoice)) {
      store.modelChoice = ''
    }
  } catch { /* The composer falls back to the active model. */ }
}

function humanClarifyWhy(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/^[a-z][a-z0-9_]*$/i.test(text)) return ''
  return text
}

export function clarificationCardFromPayload(payload = {}) {
  const groups = payload.groups || []
  return {
    caseId: payload.case_id || '',
    title: payload.title || '需要确认',
    groups: groups.map(group => ({
      questionId: group.question_id || group.id,
      prompt: group.prompt || group.question,
      why: humanClarifyWhy(group.why),
      required: group.required !== false,
      allowFreeText: Boolean(group.allow_free_text ?? group.allowFreeText),
      multiSelect: Boolean(group.multi_select ?? group.multiSelect),
      choices: (group.choices || group.options || []).map(choice => ({
        id: choice.id || choice.choice_id || choice.label,
        label: choice.label,
        explanation: choice.explanation || choice.hint || '',
        recommended: Boolean(choice.recommended),
        source: choice.source || '',
      })),
    })),
    confirmed: '',
    submitting: false,
  }
}

function archivedMessage(message) {
  if (message.role === 'user') {
    return {
      role: 'u',
      text: message.content,
      persistedId: message.id,
      runId: message.run_id || '',
    }
  }
  return {
    role: 'a',
    persistedId: message.id,
    runId: message.run_id || '',
    sessionId: message.session_id || '',
    question: '',
    eventsUrl: '',
    lastCursor: '',
    streamConnected: false,
    startedAt: 0,
    elapsed: '',
    thinking: { open: false, streaming: false, text: '' },
    steps: [],
    ledger: [],
    clarify: null,
    clarifyHistory: [],
    answer: { md: message.content, done: true, streaming: false, draft: '', usage: null, finishReason: '' },
    charts: null,
    suggestions: null,
    failure: '',
    status: 'done',
  }
}

function liveAssistantMessage(runId, sessionId, status = 'running') {
  return {
    role: 'a',
    runId,
    sessionId,
    eventsUrl: `/api/v2/runs/${encodeURIComponent(runId)}/stream`,
    lastCursor: '',
    status,
    streamConnected: false,
    startedAt: 0,
    elapsed: '',
    thinking: { open: true, streaming: false, text: '' },
    steps: [],
    ledger: [],
    clarify: null,
    clarifyHistory: [],
    answer: { md: '', done: false, streaming: false, draft: '', usage: null, finishReason: '' },
    charts: null,
    suggestions: null,
    failure: '',
  }
}

function waitingAssistantMessage(item) {
  return {
    role: 'a',
    persistedId: `clarification:${item.case_id}`,
    runId: item.run_id || '',
    sessionId: item.session_id || '',
    eventsUrl: item.events_url || `/api/v2/runs/${encodeURIComponent(item.run_id || '')}/stream`,
    lastCursor: String(item.last_event_cursor ?? ''),
    status: 'waiting_clarification',
    streamConnected: false,
    startedAt: 0,
    elapsed: '',
    thinking: { open: false, streaming: false, text: '' },
    steps: [],
    ledger: [],
    clarify: clarificationCardFromPayload(item),
    clarifyHistory: [],
    answer: { md: '', done: false, streaming: false, draft: '', usage: null, finishReason: '' },
    failure: '',
  }
}

export function restoreSessionMessages(messages = [], waitingClarifications = []) {
  const answeredRuns = new Set(messages.filter(item => item.role === 'assistant').map(item => item.run_id))
  const restored = messages.flatMap((item) => {
    const archived = archivedMessage(item)
    if (item.role === 'user' && item.run_id && !answeredRuns.has(item.run_id)) {
      // Failed and interrupted runs may never have stored an assistant row.
      // Rebuild their card so the persisted event trail can restore the result.
      return [archived, liveAssistantMessage(item.run_id, item.session_id || '', 'archived')]
    }
    return [archived]
  })
  const pending = [...waitingClarifications].sort((left, right) => {
    const leftTime = Date.parse(left.created_at || '')
    const rightTime = Date.parse(right.created_at || '')
    return (Number.isFinite(leftTime) ? leftTime : 0) - (Number.isFinite(rightTime) ? rightTime : 0)
  })
  pending.forEach((item) => {
    const waiting = waitingAssistantMessage(item)
    const archived = restored.find(message => (
      message.role === 'a' && message.runId === waiting.runId && !message.clarify
    ))
    if (archived) Object.assign(archived, waiting, { persistedId: archived.persistedId })
    else restored.push(waiting)
  })
  const questionByRun = {}
  for (const message of restored) {
    if (message.role === 'u' && message.runId && message.text) {
      questionByRun[message.runId] = message.text
    }
  }
  for (const message of restored) {
    if (message.role === 'a' && message.runId && !message.question && questionByRun[message.runId]) {
      message.question = questionByRun[message.runId]
    }
  }
  return restored
}

export async function openSession(id, { focusMessageId = '' } = {}) {
  const epoch = authEpoch
  const requestSeq = ++sessionRequestSeq
  historyController?.abort()
  const controller = new AbortController()
  historyController = controller
  const isCurrent = () => !controller.signal.aborted
    && epoch === authEpoch && requestSeq === sessionRequestSeq && store.sessionId === id
  detachCurrentStream()
  store.busy = false
  store.streamState = 'idle'
  store.sessionId = id
  store.messages = []
  store.focusMessageId = ''
  store.historyLoading = true
  store.historyError = ''
  try {
    const [messages, waitingClarifications] = await Promise.all([
      api.chatMessages(id, { signal: controller.signal }),
      api.waitingClarifications({ session_id: id }, { signal: controller.signal }),
    ])
    if (!isCurrent()) return
    store.messages = restoreSessionMessages(messages, waitingClarifications)
    store.focusMessageId = focusMessageId || [...store.messages].reverse().find(item => item.role === 'u')?.persistedId || ''
    store.focusRequest += 1
    store.streamState = waitingClarifications.length ? 'waiting' : 'idle'
    const remembered = store.liveSessions[id]
    const hasLiveCard = store.messages.some(item => item.role === 'a' && item.runId && remembered?.runId === item.runId)
    if (remembered?.runId && !hasLiveCard && LIVE_RUN_STATUSES.has(remembered.status) && remembered.status !== 'waiting_clarification') {
      store.messages.push(liveAssistantMessage(remembered.runId, id, remembered.status))
    }
    const restored = store.messages
    restored.filter(item => item.role === 'a').forEach(item => {
      item.historical = true
      item.historyLoading = Boolean(item.runId)
      item.historySignal = controller.signal
    })
    void hydrateThinkSections(restored, { sessionId: id, signal: controller.signal, isCurrent }).catch(() => {
      if (isCurrent()) restored.forEach(item => { item.historyLoading = false })
    })
  } catch (error) {
    if (!isCurrent()) return
    store.historyError = error.message || '历史对话加载失败'
    throw error
  } finally {
    if (isCurrent()) store.historyLoading = false
  }
}

async function hydrateThinkSections(messages, { sessionId, signal, isCurrent }) {
  const targets = messages.filter(message => message.role === 'a' && message.runId).reverse()
  if (!targets.length) return
  const { handleEvent, resumeLiveRun } = await import('./chat.js')

  function reconnectLive() {
    if (!isCurrent() || store.activeController) return
    const live = [...store.messages].reverse().find(item => (
      item.role === 'a' && item.runId && !item.historyLoading
      && LIVE_RUN_STATUSES.has(item.status) && item.status !== 'waiting_clarification'
    ))
    if (live) {
      live.sessionId = live.sessionId || sessionId
      live.eventsUrl = live.eventsUrl || `/api/v2/runs/${encodeURIComponent(live.runId)}/stream`
      markLiveSession(sessionId, live)
      resumeLiveRun(live)
    } else if (targets.every(item => !item.historyLoading)) {
      delete store.liveSessions[sessionId]
    }
  }

  async function hydrateMessage(message) {
    try {
      let after = 0
      let reportRequested = false
      for (;;) {
        if (!isCurrent()) return
        const page = await api.runEvents(message.runId, { after, limit: 1000 }, { signal })
        const items = page?.items || []
        for (let start = 0; start < items.length; start += 80) {
          if (!isCurrent()) return
          for (const event of items.slice(start, start + 80)) {
            if (event.type === 'report.ready' && reportRequested) {
              message.lastCursor = String(event.cursor)
              continue
            }
            if (event.type === 'report.ready') reportRequested = true
            handleEvent(message, { id: String(event.cursor), type: event.type, payload: event.payload || {} })
          }
          await yieldToBrowser()
        }
        if (!page?.has_more || !items.length) break
        const next = Number(page.next_cursor ?? items[items.length - 1].cursor)
        if (!Number.isFinite(next) || next <= after) break
        after = next
      }
      const stillLive = LIVE_RUN_STATUSES.has(message.status) && message.status !== 'waiting_clarification'
      if (!stillLive) {
        if (message.thinking) message.thinking.streaming = false
        message.steps?.forEach(step => {
          if (step.thinking) step.thinking.streaming = false
          step.tools?.forEach(tool => { if (tool.state === 'running') tool.state = 'done' })
        })
      }
    } catch (error) {
      if (isCurrent() && error.name !== 'AbortError') message.historyError = '部分历史内容未加载，重新打开会话可重试。'
    } finally {
      if (isCurrent()) message.historyLoading = false
    }
    if (message === targets[0]) reconnectLive()
  }

  let next = 0
  async function worker() {
    while (isCurrent() && next < targets.length) {
      const message = targets[next++]
      await yieldToBrowser()
      if (isCurrent()) await hydrateMessage(message)
    }
  }
  await Promise.all(Array.from({ length: Math.min(2, targets.length) }, () => worker()))
  reconnectLive()
}

export async function loadReviewCount() {
  if (!['admin', 'knowledge_reviewer'].includes(store.user?.role)) {
    store.reviewPending = 0
    return
  }
  const epoch = authEpoch
  try {
    const count = (await api.reviewQueue('pending_review')).length
    if (epoch === authEpoch) store.reviewPending = count
  }
  catch { if (epoch === authEpoch) store.reviewPending = 0 }
}

export function formatDate(value, withTime = true) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date)
}
