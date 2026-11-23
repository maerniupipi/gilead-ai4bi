import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_BRANDING, mergeBranding } from '../src/branding.js'
import { handleEvent } from '../src/chat.js'
import { clarificationCardFromPayload, isSessionLive, markLiveSession, newChat, openSession, restoreSessionMessages, store } from '../src/store.js'

const pending = {
  case_id: 'case-1',
  run_id: 'run-1',
  session_id: 'session-1',
  created_at: '2026-08-06T00:00:00Z',
  events_url: '/api/v2/runs/run-1/stream',
  last_event_cursor: 7,
  groups: [{
    question_id: 'domain',
    prompt: '请选择业务域',
    required: true,
    allow_free_text: false,
    choices: [{ id: 'actual', label: 'Actual', explanation: '实际销售口径' }],
  }],
}

test('restores a failed run even when no assistant message was stored', () => {
  const restored = restoreSessionMessages([{
    id: 'failed-question', session_id: 'session-failed', run_id: 'run-failed',
    role: 'user', content: '各个地区销量如何',
  }])
  assert.equal(restored.length, 2)
  const answer = restored[1]
  assert.equal(answer.runId, 'run-failed')
  handleEvent(answer, { id: '1', type: 'quick.failed', payload: { code: 'JOB_VALUEERROR' } })
  handleEvent(answer, { id: '2', type: 'run.status_changed', payload: { to: 'failed' } })
  assert.equal(answer.status, 'failed')
  assert.match(answer.answer.md, /JOB_VALUEERROR/)
})

test('clarification card keeps multi-select and memory recommendation', () => {
  const card = clarificationCardFromPayload({
    case_id: 'case-2',
    groups: [
      {
        id: 'caliber',
        question: '这次按哪种口径算？',
        why: '问句没钉死',
        multi_select: false,
        options: [
          { id: 'A', label: '金额', recommended: true, source: 'personal_memory', hint: '你的习惯' },
          { id: 'B', label: '盒数', recommended: false },
        ],
      },
      {
        id: 'metrics',
        question: '这次要看哪些指标？',
        multi_select: true,
        options: [
          { id: 'A', label: '销售额', recommended: true, source: 'personal_memory' },
          { id: 'B', label: '达成率', recommended: false },
        ],
      },
    ],
  })
  assert.equal(card.groups.length, 2)
  assert.equal(card.groups[0].prompt, '这次按哪种口径算？')
  assert.equal(card.groups[0].multiSelect, false)
  assert.equal(card.groups[0].choices[0].recommended, true)
  assert.equal(card.groups[0].choices[0].source, 'personal_memory')
  assert.equal(card.groups[1].multiSelect, true)
})

test('clarification card hides raw slot keys as the why line', () => {
  const card = clarificationCardFromPayload({
    groups: [{
      id: 'time_scope',
      question: '这次按哪个时间范围算？',
      why: 'time_scope',
      options: [{ id: 'A', label: '今年 YTD' }],
    }],
  })
  assert.equal(card.groups[0].prompt, '这次按哪个时间范围算？')
  assert.equal(card.groups[0].why, '')
})

test('restores a waiting clarification as a resumable assistant card', () => {
  const restored = restoreSessionMessages([{
    id: 'message-1',
    session_id: 'session-1',
    run_id: 'run-1',
    role: 'user',
    content: '今年销量是多少？',
    fact_ids: [],
  }], [pending])

  assert.equal(restored.length, 2)
  assert.equal(restored[1].status, 'waiting_clarification')
  assert.equal(restored[1].runId, 'run-1')
  assert.equal(restored[1].eventsUrl, '/api/v2/runs/run-1/stream')
  assert.equal(restored[1].lastCursor, '7')
  assert.equal(restored[1].clarify.caseId, 'case-1')
  assert.equal(restored[1].clarify.groups[0].questionId, 'domain')
  assert.equal(restored[1].clarify.groups[0].prompt, '请选择业务域')
  assert.equal(restored[1].clarify.groups[0].choices[0].id, 'actual')
  assert.equal(restored[1].clarify.groups[0].choices[0].label, 'Actual')
})

test('upgrades an archived assistant for the same run instead of duplicating it', () => {
  const restored = restoreSessionMessages([{
    id: 'message-a',
    session_id: 'session-1',
    run_id: 'run-1',
    role: 'assistant',
    content: '',
    fact_ids: [],
  }], [pending])

  assert.equal(restored.length, 1)
  assert.equal(restored[0].persistedId, 'message-a')
  assert.equal(restored[0].status, 'waiting_clarification')
  assert.equal(restored[0].clarify.caseId, 'case-1')
})

test('openSession loads pending clarification state while restoring history', async () => {
  const previousFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(String(url))
    const body = String(url).includes('/clarifications/waiting')
      ? [pending]
      : [{
          id: 'message-1',
          session_id: 'session-1',
          run_id: 'run-1',
          role: 'user',
          content: '今年销量是多少？',
          fact_ids: [],
        }]
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await openSession('session-1')

    assert.equal(store.sessionId, 'session-1')
    assert.equal(store.streamState, 'waiting')
    assert.equal(store.messages.at(-1).clarify.caseId, 'case-1')
    assert.ok(requests.includes('/api/v2/chat/sessions/session-1/messages'))
    assert.ok(requests.includes('/api/v2/clarifications/waiting?session_id=session-1'))
    assert.equal(store.focusMessageId, 'message-1')
  } finally {
    globalThis.fetch = previousFetch
    store.sessionId = ''
    store.messages = []
    store.focusMessageId = ''
    store.streamState = 'idle'
    store.busy = false
    store.liveSessions = {}
  }
})

test('openSession can pin the jumped-to user question', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    const body = String(url).includes('/clarifications/waiting')
      ? []
      : [{
          id: 'message-jump',
          session_id: 'session-jump',
          run_id: 'run-jump',
          role: 'user',
          content: '安达唐销量如何',
          fact_ids: [],
        }]
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await openSession('session-jump', { focusMessageId: 'message-jump' })
    assert.equal(store.sessionId, 'session-jump')
    assert.equal(store.focusMessageId, 'message-jump')
    assert.equal(store.messages[0].persistedId, 'message-jump')
  } finally {
    globalThis.fetch = previousFetch
    store.sessionId = ''
    store.messages = []
    store.focusMessageId = ''
    store.streamState = 'idle'
    store.busy = false
    store.liveSessions = {}
  }
})

test('newChat detaches a running stream without cancelling the live session marker', () => {
  let aborted = false
  store.sessionId = 'session-live'
  store.busy = true
  store.focusMessageId = 'message-old'
  store.messages = [{ role: 'a', runId: 'run-9', status: 'running', eventsUrl: '/api/v2/runs/run-9/stream' }]
  store.activeController = { abort() { aborted = true } }

  newChat()

  assert.equal(aborted, true)
  assert.equal(store.busy, false)
  assert.equal(store.sessionId, '')
  assert.equal(store.messages.length, 0)
  assert.equal(store.focusMessageId, '')
  assert.equal(isSessionLive('session-live'), true)
  store.liveSessions = {}
  store.activeController = null
})

test('openSession is not blocked by another conversation being in flight', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    const body = String(url).includes('/clarifications/waiting')
      ? []
      : [{
          id: 'message-2',
          session_id: 'session-2',
          run_id: 'run-2',
          role: 'user',
          content: '盒数呢？',
          fact_ids: [],
        }]
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  store.busy = true
  store.sessionId = 'session-busy'
  store.messages = [{ role: 'a', runId: 'run-busy', status: 'running' }]
  store.activeController = { abort() {} }
  try {
    await openSession('session-2')
    assert.equal(store.sessionId, 'session-2')
    assert.equal(store.messages[0].text, '盒数呢？')
    assert.equal(isSessionLive('session-busy'), true)
  } finally {
    globalThis.fetch = previousFetch
    store.sessionId = ''
    store.messages = []
    store.busy = false
    store.streamState = 'idle'
    store.liveSessions = {}
    store.activeController = null
  }
})

async function waitForHistory(predicate) {
  const deadline = Date.now() + 1500
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('history did not settle')
    await new Promise(resolve => setTimeout(resolve, 5))
  }
}

test('history opens at the latest question before slow event restoration completes', async () => {
  const previousFetch = globalThis.fetch
  const pendingEvents = []
  const messages = [
    { id: 'question-old', role: 'user', content: '旧问题', run_id: 'run-old' },
    { id: 'answer-old', role: 'assistant', content: '旧回答', run_id: 'run-old' },
    { id: 'question-latest', role: 'user', content: '最新问题', run_id: 'run-latest' },
    { id: 'answer-latest', role: 'assistant', content: '最新回答', run_id: 'run-latest' },
  ]
  const response = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
  globalThis.fetch = async url => {
    if (String(url).includes('/events')) return new Promise(resolve => pendingEvents.push({ url: String(url), resolve }))
    return response(String(url).includes('/clarifications/waiting') ? [] : messages)
  }
  try {
    const opening = openSession('history-slow')
    assert.equal(store.sessionId, 'history-slow')
    assert.equal(store.historyLoading, true)
    assert.equal(store.messages.length, 0)
    await opening
    assert.equal(store.historyLoading, false)
    assert.equal(store.focusMessageId, 'question-latest')
    assert.equal(store.messages.at(-1).answer.md, '最新回答')
    assert.equal(store.messages.at(-1).historyLoading, true)
    await waitForHistory(() => pendingEvents.length === 2)
    assert.match(pendingEvents[0].url, /run-latest/)
    pendingEvents[0].resolve(response({ items: [{ cursor: 1, type: 'agent.done', payload: { answer: '最新回答' } }], has_more: false }))
    await waitForHistory(() => !store.messages.at(-1).historyLoading)
    assert.equal(store.messages[1].historyLoading, true)
    pendingEvents[1].resolve(response({ items: [{ cursor: 1, type: 'agent.done', payload: { answer: '旧回答' } }], has_more: false }))
    await waitForHistory(() => !store.messages[1].historyLoading)
  } finally {
    newChat()
    pendingEvents.forEach(item => item.resolve(response({ items: [], has_more: false })))
    globalThis.fetch = previousFetch
  }
})

test('switching history cancels the previous request and discards stale messages', async () => {
  const previousFetch = globalThis.fetch
  let slowSignal
  const response = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
  globalThis.fetch = async (url, options) => {
    if (String(url).includes('/history-old/messages')) {
      slowSignal = options.signal
      return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true }))
    }
    return response(String(url).includes('/clarifications/waiting') ? [] : [
      { id: 'question-new', role: 'user', content: '新会话' },
    ])
  }
  try {
    const old = openSession('history-old')
    await openSession('history-new')
    await old
    assert.equal(slowSignal.aborted, true)
    assert.equal(store.sessionId, 'history-new')
    assert.equal(store.focusMessageId, 'question-new')
    assert.equal(store.messages[0].text, '新会话')
    assert.equal(store.historyLoading, false)
  } finally {
    newChat()
    globalThis.fetch = previousFetch
  }
})

test('failed history requests leave the loading state and allow a new conversation', async () => {
  const previousFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ error: { message: '读取失败' } }), {
    status: 500, headers: { 'Content-Type': 'application/json' },
  })
  try {
    await assert.rejects(openSession('history-error'), /读取失败/)
    assert.equal(store.historyLoading, false)
    assert.equal(store.historyError, '读取失败')
    newChat()
    assert.equal(store.historyError, '')
  } finally {
    newChat()
    globalThis.fetch = previousFetch
  }
})

test('markLiveSession clears once the run is terminal', () => {
  markLiveSession('session-x', { runId: 'run-x', status: 'running' })
  assert.equal(isSessionLive('session-x'), true)
  markLiveSession('session-x', { runId: 'run-x', status: 'done' })
  assert.equal(isSessionLive('session-x'), false)
})

test('mergeBranding keeps default business tokens when the payload omits them', () => {
  const merged = mergeBranding({ character_name: '小柯', theme_id: 'harbor', tokens: { accent: '#1a5f7a' } })
  assert.equal(merged.character_name, '小柯')
  assert.equal(merged.company_intro, DEFAULT_BRANDING.company_intro)
  assert.equal(merged.tokens.accent, '#1a5f7a')
  assert.equal(merged.tokens['accent-rgb'], DEFAULT_BRANDING.tokens['accent-rgb'])
})
