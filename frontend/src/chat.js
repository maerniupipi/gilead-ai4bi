import { reactive } from 'vue'
import { updateContext } from './context.js'
import { api, ApiError, streamRunEvents } from './api/backend.js'
import { abortableDelay } from './api/sse.js'
import { labDisplayName } from './lib/labConnection.js'
import { clarificationCardFromPayload, loadSessions, markLiveSession, showToast, store } from './store.js'

const TERMINAL_STATUSES = new Set(['partial', 'completed', 'failed', 'cancelled', 'done'])

const TOOL_META = {
  ask_lab: { label: '实验室', tone: 'lab' },
  inspect_schema: { label: '表结构', tone: 'lab' },
  generate_sql: { label: 'SQL生成', tone: 'lab' },
  validate_sql: { label: 'SQL校验', tone: 'lab' },
  query_db: { label: '数据库查询', tone: 'sql' },
  inspect_workbook: { label: '工作簿检查', tone: 'sql' },
  export_xlsx: { label: 'xlsx导出', tone: 'xlsx' },
  render_report: { label: '交互HTML报告', tone: 'xlsx' },
  present_chart: { label: '经营图表', tone: 'xlsx' },
  knowledge_search: { label: '知识检索', tone: 'knowledge' },
  bailian_recall: { label: '百炼召回', tone: 'knowledge' },
  field_recall: { label: '字段召回', tone: 'knowledge' },
  value_recall: { label: '取值召回', tone: 'knowledge' },
  knowledge_read: { label: '知识阅读', tone: 'knowledge' },
  memory_save: { label: '知识沉淀', tone: 'memory' },
  ask_user: { label: '澄清', tone: 'ask' },
  update_ledger: { label: '台账', tone: 'ask' },
  agent_lab_sql: { label: '实验室智能体', tone: 'agent' },
  agent_bailian: { label: '召回智能体', tone: 'agent' },
}

function uuid() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

// Composer choices for this run: model pick + thinking switch/intensity.
// "default" thinking means "keep the model's configured behaviour" and is
// omitted from the request entirely.
export function currentModelOptions() {
  const options = {}
  if (store.modelChoice) options.model_config_id = store.modelChoice
  if (store.thinking && store.thinking !== 'default') {
    options.thinking = store.thinking
    if (store.thinking === 'on') options.thinking_level = store.thinkingLevel || 'medium'
  }
  return options
}

function createAssistantMessage() {
  return reactive({
    role: 'a',
    runId: '',
    sessionId: '',
    question: '',
    eventsUrl: '',
    lastCursor: '',
    status: 'starting',
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
    report: null,
    reportState: {},
    failure: '',
  })
}

function clarifyCards(message) {
  return [message.clarify, ...(message.clarifyHistory || [])].filter(Boolean)
}

function archiveClarify(message) {
  if (!message.clarify) return
  if (!Array.isArray(message.clarifyHistory)) message.clarifyHistory = []
  const caseId = message.clarify.caseId
  if (caseId && message.clarifyHistory.some(item => item.caseId === caseId)) return
  message.clarifyHistory.push(message.clarify)
}

export function applyClarifyOpened(message, payload = {}) {
  const next = clarificationCardFromPayload(payload)
  if (message.clarify && message.clarify.caseId && next.caseId && message.clarify.caseId !== next.caseId) {
    archiveClarify(message)
  }
  message.status = 'waiting_clarification'
  // Any streamed narration so far was process text, not the answer.
  message.answer.draft = ''
  message.answer.streaming = false
  message.clarify = next
}

function findClarifyCard(message, caseId) {
  const cards = clarifyCards(message)
  if (caseId) return cards.find(item => item.caseId === caseId) || null
  return message.clarify || null
}

function isParkedForClarify(message) {
  return message.status === 'waiting_clarification' && Boolean(message.clarify) && !message.clarify.confirmed
}

function needsClarifyHydrate(message) {
  return message.status === 'waiting_clarification' && (!message.clarify || Boolean(message.clarify.confirmed))
}

async function hydrateWaitingClarify(message) {
  if (!message.runId || message._hydratingClarify) return
  message._hydratingClarify = true
  try {
    const waiting = await api.waitingClarifications({ run_id: message.runId })
    const currentId = message.clarify?.caseId
    // Never reopen the card the user already confirmed; only a newer waiting
    // case (the next ask_user round) should replace the dialog.
    const item = (waiting || []).find(row => row.case_id && row.case_id !== currentId)
      || (!currentId ? (waiting || []).find(row => row.case_id) : null)
    if (!item?.case_id) return
    applyClarifyOpened(message, item)
  } catch {
    /* The live stream may still deliver ask_user.opened. */
  } finally {
    message._hydratingClarify = false
  }
}

function queueClarifyHydrate(message) {
  if (!needsClarifyHydrate(message)) return
  void hydrateWaitingClarify(message)
}

function toolSummary(name, args = {}) {
  switch (name) {
    case 'ask_lab': {
      const lab = labDisplayName(args.lab_id) || args.lab_id || ''
      return `调用实验室 ${lab}：${args.question || ''}`
    }
    case 'inspect_schema':
      return args.tables?.length ? `读取表结构：${[].concat(args.tables).join('、')}` : '读取已勾选表结构'
    case 'generate_sql':
      return `本地生成 SQL：${args.question || ''}`
    case 'validate_sql':
      return '校验 SQL'
    case 'query_db':
      return '执行只读 SQL 查询'
    case 'field_recall':
      return `字段召回：${args.query || ''}`
    case 'value_recall':
      return `取值召回：${args.query || ''}`
    case 'export_xlsx':
      return `导出完整结果：${args.title || ''}`
    case 'knowledge_search':
      return `检索知识：${args.query || ''}`
    case 'bailian_recall':
      return `百炼召回 ${args.lab_type || ''}：${args.query || ''}`
    case 'knowledge_read':
      return args.path ? `阅读知识文档 ${args.path}` : '浏览知识目录'
    case 'memory_save':
      return args.scope === 'review'
        ? `提交知识审核：${args.title || ''}`
        : `写入个人记忆：${(args.content || '').slice(0, 40)}`
    case 'ask_user':
      return `向用户澄清：${args.question || ''}`
    case 'update_ledger':
      return `台账：${args.key || ''} → ${(args.text || '').slice(0, 40)}`
    case 'agent_lab_sql':
      return `委托实验室智能体：${args.question || ''}`
    case 'agent_bailian':
      return `委托召回智能体：${args.query || args.question || ''}`
    default:
      return name
  }
}

function pushStep(message, step) {
  if (!message.steps) message.steps = []
  message.steps.push(step)
  return step
}

function stepByNumber(message, step) {
  if (!message.steps) message.steps = []
  let found = message.steps.find(entry => entry.step === step)
  if (!found) {
    found = reactive({
      kind: 'step',
      step,
      open: true,
      thinking: { streaming: true, text: '' },
      content: '',
      tools: [],
      usage: null,
    })
    message.steps.push(found)
  }
  return found
}

function findToolByCallId(message, callId) {
  for (const step of message.steps || []) {
    for (const tool of step.tools || []) {
      if (tool.callId === callId) return tool
      if (tool.child) {
        const nested = findToolByCallId(tool.child, callId)
        if (nested) return nested
      }
    }
  }
  return null
}

function ensureChildMessage(tool, payload = {}) {
  if (!tool.child) {
    tool.kind = 'agent'
    tool.tone = tool.tone === 'agent' ? tool.tone : 'agent'
    tool.open = true
    tool.child = reactive({
      role: 'a',
      status: 'running',
      agentName: payload.agent_name || tool.label,
      thinkOpen: true,
      keepStepsOpen: true,
      thinking: { open: true, streaming: false, text: '' },
      steps: [],
      ledger: [],
      answer: { md: '', done: false, streaming: false, draft: '', usage: null, finishReason: '' },
      clarify: null,
      clarifyHistory: [],
      failure: '',
    })
  }
  return tool.child
}

export function handleEvent(message, event, root = message) {
  const { id, type, payload = {} } = event
  if (id && message === root) message.lastCursor = id
  if (payload.parent_call_id && message === root) {
    const tool = findToolByCallId(root, payload.parent_call_id)
    if (tool) {
      const child = ensureChildMessage(tool, payload)
      handleEvent(child, { ...event, payload: { ...payload, parent_call_id: '' } }, root)
      return
    }
    // Nested events must not mark the root turn done/failed if the parent
    // tool card is missing (e.g. late replay); otherwise the stream loop exits
    // early and can miss a trailing chart.ready.
    if (type === 'agent.done' || type === 'agent.failed' || type === 'agent.turn_start' || type === 'agent.turn_end') {
      return
    }
  }
  switch (type) {
    case 'context.updated':
    case 'context.compacted':
      if (message === root && !payload.parent_call_id) updateContext(message, event)
      break
    case 'run.created':
      message.status = payload.status || message.status
      message.modelOptions = { ...(message.modelOptions || {}), mode: payload.mode || 'normal' }
      break
    case 'agent.turn_start':
      message.status = 'running'
      message.startedAt = message.startedAt || Date.now()
      message.thinking.streaming = true
      break
    case 'agent.step_start': {
      message.status = 'running'
      message.startedAt = message.startedAt || Date.now()
      // A new step lands on top: collapse every earlier step so the trail
      // stays glanceable; users can still expand any of them manually.
      message.steps.forEach(entry => {
        if (entry.step !== payload.step) entry.open = false
      })
      const entry = stepByNumber(message, payload.step)
      entry.thinking.streaming = true
      break
    }
    case 'agent.think.delta': {
      const entry = message.steps.length ? message.steps[message.steps.length - 1] : null
      if (entry) entry.thinking.text += payload.text || ''
      else message.thinking.text += payload.text || ''
      break
    }
    case 'agent.content.delta':
      message.answer.streaming = true
      message.answer.draft += payload.text || ''
      break
    case 'assistant.message': {
      const entry = stepByNumber(message, payload.step)
      entry.thinking.text = payload.reasoning || entry.thinking.text
      entry.thinking.streaming = false
      entry.content = payload.content || ''
      entry.usage = payload.usage || null
      if ((payload.tool_calls || []).length) {
        // Intermediate narration belongs to the step card; the answer area is
        // reserved for the final summary emitted once the run completes.
        message.answer.draft = ''
        message.answer.streaming = false
      } else if (payload.content) {
        message.answer.md = payload.content
        message.answer.streaming = false
        message.answer.draft = ''
        message.answer.finishReason = payload.finish_reason || ''
        message.answer.usage = payload.usage || null
      }
      break
    }
    case 'tool.call': {
      const entry = payload.step ? stepByNumber(message, payload.step) : pushStep(message, { kind: 'step', tools: [] })
      const meta = TOOL_META[payload.name] || { label: payload.name, tone: 'tool' }
      entry.tools.push({
        callId: payload.call_id,
        name: payload.name,
        label: meta.label,
        tone: meta.tone,
        kind: payload.kind === 'agent' || meta.tone === 'agent' ? 'agent' : 'tool',
        summary: toolSummary(payload.name, payload.arguments || {}),
        arguments: payload.arguments || {},
        state: 'running',
        ok: null,
        output: '',
        preview: null,
        open: meta.tone === 'agent',
        child: payload.child || null,
      })
      break
    }
    case 'tool.result': {
      const entry = message.steps?.slice().reverse().find(step => step.tools?.some(tool => tool.callId === payload.call_id))
      const tool = entry?.tools.find(item => item.callId === payload.call_id)
      if (tool) {
        tool.state = 'done'
        tool.ok = Boolean(payload.ok)
        tool.output = payload.output || ''
        tool.preview = payload.preview || null
      }
      break
    }
    case 'ask_user.opened':
      applyClarifyOpened(message, payload)
      break
    case 'ask_user.answered': {
      message.status = 'running'
      const card = findClarifyCard(message, payload.case_id)
      if (card) card.confirmed = card.confirmed || payload.answer || '已回答'
      break
    }
    case 'memory.auto_saved': {
      // The clarification conclusion was persisted into personal memory.
      const card = findClarifyCard(message, payload.case_id)
      if (card) card.memorySaved = true
      break
    }
    case 'run.status_changed':
      message.status = payload.to || message.status
      if (payload.to === 'waiting_clarification') queueClarifyHydrate(message)
      if (payload.to === 'failed' && !message.answer.md && !message.failure) {
        message.failure = '本次分析失败，请查看运行轨迹中的失败原因后重试。'
        message.answer.done = true
        message.answer.streaming = false
        message.thinking.streaming = false
      }
      break
    case 'agent.ledger.updated':
      // Progress ledger snapshot: scopes, established facts, conclusions.
      message.ledger = Array.isArray(payload.entries) ? payload.entries : []
      break
    case 'agent.done':
      // Only the root turn's final answer closes the bubble; nested agent.done
      // is routed away above via parent_call_id.
      message.answer.md = payload.answer || message.answer.md
      message.answer.done = true
      message.answer.streaming = false
      message.status = 'done'
      message.thinking.streaming = false
      break
    case 'chart.ready': {
      const charts = Array.isArray(payload.charts) ? payload.charts : []
      if (charts.length) {
        // Detach from the live SSE payload so Vue/ECharts never hold a
        // reactive Proxy into chart options (structuredClone/setOption can hang).
        try {
          message.charts = JSON.parse(JSON.stringify({
            ...payload,
            default_type: payload.default_type || charts[0]?.type || '',
            charts,
          }))
        } catch {
          message.charts = {
            ...payload,
            default_type: payload.default_type || charts[0]?.type || '',
            charts,
          }
        }
        if (payload.version === 2) {
          const cursor = Number(id)
          message.charts.event_cursor = Number.isSafeInteger(cursor) && cursor > 0 ? cursor : undefined
          const cards = [...(message.chartCards || [])]
          const index = cards.findIndex(card => card.event_cursor === message.charts.event_cursor)
          if (index < 0) cards.push(message.charts)
          else cards[index] = message.charts
          message.chartCards = cards
        }
        // Keep the answer card visible even if markdown was empty briefly.
        // Do not flip message.status here — wait for agent.done so stop/pause
        // and suggest.ready stay sequenced correctly.
        message.answer.done = true
      }
      break
    }
    case 'suggest.ready': {
      const questions = Array.isArray(payload.questions) ? payload.questions : []
      const texts = questions
        .map(item => (typeof item === 'string' ? item : item?.text || ''))
        .map(text => String(text || '').trim())
        .filter(Boolean)
        .slice(0, 3)
      if (texts.length === 3) {
        message.suggestions = { category: payload.category || '', questions: texts }
      }
      break
    }
    case 'report.ready': {
      message.reportLoading = true
      message.reportError = ''
      const requestId = (message.reportRequestId || 0) + 1
      message.reportRequestId = requestId
      api.runReport(payload.run_id || message.runId, { signal: root.historySignal }).then(report => {
        if (message.reportRequestId === requestId) message.report = report
      }).catch(error => {
        if (message.reportRequestId === requestId && error.name !== 'AbortError') message.reportError = error.message || '报告加载失败'
      }).finally(() => {
        if (message.reportRequestId === requestId) message.reportLoading = false
      })
      break
    }
    case 'agent.failed':
      message.status = 'failed'
      message.failure = payload.message || payload.code || '未知错误'
      message.answer.done = true
      message.thinking.streaming = false
      break
    case 'quick.done':
      message.answer.done = true
      message.status = payload.status || 'done'
      if (message.status === 'failed' && !message.answer.md) {
        message.answer.md = '> 未能生成答案，请在运行轨迹中查看失败原因。'
      }
      break
    case 'job.failed':
    case 'quick.failed':
      message.status = 'failed'
      message.answer.done = true
      message.answer.streaming = false
      message.thinking.streaming = false
      message.failure = payload.message === 'Durable Quick job failed closed'
        ? `后台分析失败（${payload.code || '未知错误'}），请在运行轨迹中查看详情后重试。`
        : payload.message || `后台分析失败（${payload.code || '未知错误'}），请查看运行轨迹。`
      if (!message.answer.md) {
        message.answer.md = `> ${message.failure}`
        message.failure = ''
      }
      break
  }
}

export function startElapsedTicker(message) {
  if (message._elapsedTimer) return
  message._elapsedTimer = setInterval(() => {
    if (!message.startedAt) return
    if (TERMINAL_STATUSES.has(message.status) || message.status === 'waiting_clarification') {
      clearInterval(message._elapsedTimer)
      message._elapsedTimer = null
      return
    }
    message.elapsed = `${Math.max(1, Math.round((Date.now() - message.startedAt) / 1000))}s`
  }, 1000)
}

function friendlyError(error, phase = '请求', { chatRoute = false } = {}) {
  if (error?.name === 'AbortError') return ''
  if (error instanceof ApiError && error.status === 404 && chatRoute) {
    return 'Quick Chat API 尚未在服务端启用（`/api/v2/chat` 返回 404）。请联系管理员挂载 chat 路由。'
  }
  if (error instanceof ApiError && error.status === 404) return `${phase}失败：目标不存在或已过期。`
  if (error instanceof ApiError && error.status === 403) return '当前账号没有执行此操作的权限。'
  return `${phase}失败：${error?.message || '网络连接异常'}`
}

async function connectMessage(message, controller) {
  message.streamConnected = true
  store.streamState = message.status === 'waiting_clarification' ? 'waiting' : 'connected'
  startElapsedTicker(message)
  try {
    for (let cleanClose = 0; cleanClose <= 4; cleanClose += 1) {
      await streamRunEvents(message.eventsUrl, {
        signal: controller.signal,
        lastEventId: message.lastCursor,
        onHeartbeat: () => { store.streamState = 'connected' },
        onEvent: event => handleEvent(message, event),
      })
      if (controller.signal.aborted) return
      await catchUpEvents(message)
      if (TERMINAL_STATUSES.has(message.status) || isParkedForClarify(message)) return
      if (needsClarifyHydrate(message)) {
        await hydrateWaitingClarify(message)
        if (isParkedForClarify(message)) return
      }

      const run = await api.run(message.runId)
      message.status = run.status || message.status
      if (needsClarifyHydrate(message)) await hydrateWaitingClarify(message)
      await catchUpEvents(message)
      if (TERMINAL_STATUSES.has(message.status) || isParkedForClarify(message)) return
      if (cleanClose === 4) throw new Error('事件流提前关闭，重连次数已用尽')
      store.streamState = 'reconnecting'
      await abortableDelay(Math.min(700 * (cleanClose + 1), 2500), controller.signal)
    }
  } finally {
    message.streamConnected = false
  }
}

async function catchUpEvents(message) {
  let after = Number(message.lastCursor || 0)
  for (;;) {
    const page = await api.runEvents(message.runId, { after, limit: 1000 })
    const items = page?.items || []
    items.forEach(event => handleEvent(message, { id: String(event.cursor), type: event.type, payload: event.payload }))
    if (!page?.has_more || !items.length) return
    const next = Number(page.next_cursor ?? items[items.length - 1].cursor)
    if (!Number.isFinite(next) || next <= after) return
    after = next
  }
}

export async function sendQuestion(text, insightOptions = null, reportContext = null) {
  const question = text.trim()
  if (store.busy || !question) return
  if (!store.token) {
    store.loginOpen = true
    showToast('请先登录')
    return
  }

  if (!store.chatbotId) {
    store.chatbotChooserOpen = true
    showToast('请先选择一个 Chatbot')
    return
  }

  store.focusMessageId = ''
  store.messages.push({ role: 'u', text: question })
  const message = createAssistantMessage()
  message.question = question
  store.messages.push(message)
  store.busy = true
  store.streamState = 'starting'
  const controller = new AbortController()
  store.activeController = controller

  try {
    const modelOptions = { ...currentModelOptions() }
    modelOptions.chatbot_id = store.chatbotId
    if (reportContext) modelOptions.report_context = reportContext
    if (insightOptions && insightOptions.mode === 'insight') {
      modelOptions.mode = 'insight'
      store.insightMode = true
    } else {
      store.insightMode = false
    }
    if (insightOptions?.customPrompt) modelOptions.insight_custom_prompt = insightOptions.customPrompt
    if (insightOptions?.skillPackId) modelOptions.insight_skill_pack_id = insightOptions.skillPackId
    message.modelOptions = modelOptions
    const accepted = await api.createChat(question, store.sessionId, uuid(), modelOptions)
    message.runId = accepted.run_id
    message.sessionId = accepted.session_id
    message.question = question
    message.eventsUrl = accepted.events_url || `/api/v2/runs/${accepted.run_id}/stream`
    message.status = accepted.status || 'accepted'
    markLiveSession(accepted.session_id, message)
    if (!store.messages.includes(message) || store.activeController !== controller) {
      return
    }
    store.sessionId = accepted.session_id
    await connectMessage(message, controller)
  } catch (error) {
    const friendly = friendlyError(error, message.runId ? '事件流' : '分析', { chatRoute: !message.runId })
    if (friendly) {
      if (message.clarify?.confirmed) {
        message.clarify.reconnectError = friendly
        showToast(`口径已提交，但${friendly}`)
      } else {
        message.answer.md ||= `> ${friendly}`
        message.answer.done = true
        message.status = 'failed'
        message.thinking.streaming = false
      }
    }
  } finally {
    if (store.activeController === controller) {
      store.activeController = null
      store.busy = false
      store.streamState = message.status === 'waiting_clarification' ? 'waiting' : 'idle'
    }
    if (message.sessionId) markLiveSession(message.sessionId, message)
    loadSessions().catch(() => {})
  }
}

export async function resumeLiveRun(message) {
  const sessionId = message.sessionId || store.sessionId
  if (!message?.eventsUrl || message.streamConnected) return
  if (!sessionId || store.sessionId !== sessionId) return
  if (store.activeController) return
  const controller = new AbortController()
  store.activeController = controller
  store.busy = true
  store.streamState = 'starting'
  try {
    if (store.sessionId !== sessionId || store.activeController !== controller) return
    await connectMessage(message, controller)
  } catch (error) {
    const notice = friendlyError(error, '事件流')
    if (notice) showToast(notice)
  } finally {
    if (store.activeController === controller) {
      store.activeController = null
      store.busy = false
      store.streamState = message.status === 'waiting_clarification' ? 'waiting' : 'idle'
    }
    if (sessionId) markLiveSession(sessionId, message)
  }
}

function resumeModelOptions(options = {}) {
  // ClarificationSubmitRequest forbids extras; insight chat stores mode /
  // skill pack on the message but those must not go on the answers POST.
  const out = {}
  if (options.model_config_id) out.model_config_id = options.model_config_id
  if (options.thinking) out.thinking = options.thinking
  if (options.thinking_level) out.thinking_level = options.thinking_level
  if (options.use_memory === true || options.use_memory === false) {
    out.use_memory = options.use_memory
  }
  return out
}

export async function confirmClarify(message, answers, summary) {
  const clarification = message.clarify
  if (!clarification || clarification.submitting) return
  clarification.submitting = true
  try {
    await api.clarify(
      clarification.caseId,
      answers,
      resumeModelOptions(message.modelOptions || {}),
    )
  } catch (error) {
    showToast(friendlyError(error, '澄清提交'))
    return
  } finally {
    clarification.submitting = false
  }
  clarification.confirmed = summary
  clarification.reconnectError = ''
  message.status = 'resuming'
  showToast('口径已确认，正在继续分析')
  if (!message.streamConnected && message.eventsUrl) await retryClarificationStream(message)
}

export async function retryClarificationStream(message) {
  if (!message.clarify || message.streamConnected || !message.eventsUrl || store.busy || store.activeController) return
  const controller = new AbortController()
  store.activeController = controller
  store.busy = true
  message.clarify.reconnectError = ''
  try {
    await connectMessage(message, controller)
  } catch (error) {
    const notice = friendlyError(error, '事件流重连')
    if (notice) {
      message.clarify.reconnectError = notice
      showToast(`口径已提交，但${notice}`)
    }
  } finally {
    if (store.activeController === controller) {
      store.activeController = null
      store.busy = false
      store.streamState = message.status === 'waiting_clarification' ? 'waiting' : 'idle'
    }
  }
}
