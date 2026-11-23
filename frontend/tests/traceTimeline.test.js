import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildTimeline,
  buildConversation,
  buildGantt,
  buildSessionModel,
  compactJson,
  filterItems,
  formatDuration,
  highlightJson,
  insertTurnHeaders,
  oneLine,
} from '../src/utils/traceTimeline.js'

function event(cursor, type, payload = {}, created_at = `2026-08-21T09:00:0${Math.min(cursor, 9)}Z`) {
  return { cursor, type, payload, created_at }
}

const SAMPLE = [
  event(1, 'run.created', { question: '安达唐销量' }),
  event(2, 'job.enqueued', { kind: 'start_quick' }),
  event(3, 'job.claimed', {}),
  event(4, 'agent.turn_start', { question: '后续问安达唐时默认过滤重点民营机构' }),
  event(5, 'agent.step_start', { step: 1 }),
  event(6, 'agent.think.delta', { step: 1, text: '先读记忆' }),
  event(7, 'agent.think.delta', { step: 1, text: '再检索' }),
  event(8, 'assistant.message', {
    step: 1,
    content: '用户希望后续问安达唐时默认过滤重点民营机构',
    reasoning: '这是个人偏好，我应该先读取记忆',
    finish_reason: 'tool_calls',
    usage: { total_tokens: 120 },
    tool_calls: [{ call_id: 'c1', name: 'knowledge_search' }],
  }),
  event(9, 'tool.call', {
    call_id: 'c1', name: 'knowledge_search', step: 1,
    arguments: { query: '安达唐 重点民营机构' },
  }),
  event(10, 'tool.result', {
    call_id: 'c1', name: 'knowledge_search', step: 1, ok: true,
    output: '未检索到相关知识。可用 knowledge_read 浏览目录。',
  }),
  event(11, 'agent.ledger.updated', { entries: [{ kind: 'scope', text: '重点民营机构', key: 'scope' }] }),
  event(12, 'agent.ledger.updated', { entries: [
    { kind: 'scope', text: '重点民营机构', key: 'scope' },
    { kind: 'term', text: '安达唐 = Forxiga', key: '安达唐' },
  ] }),
  event(13, 'tool.call', {
    call_id: 'c2', name: 'update_ledger', step: 1,
    arguments: { key: '安达唐', kind: 'term', text: '安达唐 = Forxiga' },
  }),
  event(14, 'tool.result', {
    call_id: 'c2', name: 'update_ledger', step: 1, ok: true,
    output: '已更新进度台账：安达唐（术语映射）。',
  }),
  event(15, 'agent.ledger.updated', { entries: [
    { kind: 'scope', text: '重点民营机构', key: 'scope' },
    { kind: 'term', text: '安达唐 = Forxiga', key: '安达唐' },
  ] }),
  event(16, 'agent.step_start', { step: 2 }),
  event(17, 'assistant.message', {
    step: 2,
    content: '已记住这个偏好。',
    reasoning: '',
    finish_reason: 'stop',
    usage: { total_tokens: 80 },
    tool_calls: [],
  }),
  event(18, 'agent.done', { answer: '已记住这个偏好。' }),
  event(19, 'job.succeeded', {}),
  event(20, 'run.status_changed', { status: 'completed' }),
]

test('oneLine collapses whitespace, strips markdown and truncates', () => {
  assert.equal(oneLine('  a\n b  '), 'a b')
  assert.equal(oneLine('abcdefghij', 8), 'abcdefg…')
  assert.equal(oneLine('明白了，您说的"BU"是指**渠道**维度'), '明白了，您说的"BU"是指渠道维度')
})

test('compactJson stringifies and truncates objects', () => {
  assert.equal(compactJson({ query: '耐口' }), '{"query":"耐口"}')
  assert.equal(compactJson({}), '')
})

test('formatDuration uses Chinese units', () => {
  assert.equal(formatDuration(20), '20 毫秒')
  assert.equal(formatDuration(12_000), '12 秒')
  assert.equal(formatDuration(90_000), '1 分 30 秒')
})

test('highlightJson escapes markup and paints keys', () => {
  const html = highlightJson({ action: 'read', n: 1 })
  assert.match(html, /json-key/)
  assert.match(html, /json-str/)
  assert.match(html, /json-num/)
  assert.equal(highlightJson('<script>'), '&lt;script&gt;')
})

test('timeline drops deltas, jobs and step markers', () => {
  const { items, calls, turns } = buildTimeline(SAMPLE)
  assert.equal(turns, 1)
  assert.equal(calls, 2)
  assert.deepEqual(items.map((item) => `${item.role}:${item.kind}`), [
    'user:question',
    'assistant:message',
    'tool:call',
    'context:ledger',
    'tool:call',
    'assistant:answer',
  ])
  assert.ok(!items.some((item) => item.type === 'agent.think.delta'))
  assert.ok(!items.some((item) => item.type === 'job.enqueued'))
})

test('tool.call and tool.result merge into one row with a result preview', () => {
  const tool = buildTimeline(SAMPLE).items.find((item) => item.name === 'knowledge_search')
  assert.equal(tool.status, 'completed')
  assert.equal(tool.ok, true)
  assert.equal(tool.detail, '{"query":"安达唐 重点民营机构"}')
  assert.match(tool.resultPreview, /未检索到相关知识/)
  assert.equal(tool.headline, '知识检索')
})

test('consecutive ledger snapshots collapse, and the one after update_ledger is skipped', () => {
  const ledgers = buildTimeline(SAMPLE).items.filter((item) => item.kind === 'ledger')
  assert.equal(ledgers.length, 1)
  assert.equal(ledgers[0].updates, 2)
  assert.match(ledgers[0].headline, /2 次/)
})

test('run.created is used as the user turn only when turn_start is missing', () => {
  const withStart = buildTimeline(SAMPLE).items.filter((item) => item.role === 'user')
  assert.equal(withStart.length, 1)
  assert.match(withStart[0].headline, /安达唐/)

  const orphan = buildTimeline([
    event(1, 'run.created', { question: '耐口销量' }),
    event(2, 'assistant.message', { step: 1, content: '好', tool_calls: [] }),
  ])
  assert.equal(orphan.items[0].role, 'user')
  assert.equal(orphan.items[0].headline, '耐口销量')
})

test('agent.done is skipped when it repeats the last answer', () => {
  const answers = buildTimeline(SAMPLE).items.filter((item) => item.kind === 'answer')
  assert.equal(answers.length, 1)
  assert.equal(answers[0].content, '已记住这个偏好。')
})

test('conversation keeps user questions and final answers only', () => {
  const { items } = buildTimeline(SAMPLE)
  const talk = buildConversation(items)
  assert.deepEqual(talk.map((item) => item.role), ['user', 'assistant'])
})

test('insertTurnHeaders injects a marker before the first item of each turn', () => {
  const rows = insertTurnHeaders(buildTimeline(SAMPLE).items)
  assert.equal(rows[0].rowKind, 'turn')
  assert.equal(rows[0].turn, 1)
  assert.equal(rows[1].rowKind, 'item')
})

test('search matches tool arguments and Chinese labels', () => {
  const { items } = buildTimeline(SAMPLE)
  const hits = filterItems(items, '知识检索')
  assert.equal(hits.length, 1)
  assert.equal(hits[0].name, 'knowledge_search')
  assert.equal(filterItems(items, '不存在的词').length, 0)
})

test('gantt places user, model and tool bars', () => {
  const model = buildSessionModel(SAMPLE, {
    created_at: '2026-08-21T09:00:00Z',
    updated_at: '2026-08-21T09:01:00Z',
  })
  assert.ok(model.gantt.input.length)
  assert.ok(model.gantt.model.length)
  assert.ok(model.gantt.tools.length)
  assert.equal(model.durationMs, 60_000)
  assert.equal(model.calls, 2)
})

test('failed tool stays a single row marked failed', () => {
  const { items } = buildTimeline([
    event(1, 'agent.turn_start', { question: '查一下' }),
    event(2, 'tool.call', { call_id: 'x', name: 'query_db', arguments: { sql: 'select 1' } }),
    event(3, 'tool.result', { call_id: 'x', name: 'query_db', ok: false, output: 'SQL 执行失败' }),
  ])
  assert.equal(items[1].status, 'failed')
  assert.equal(items[1].ok, false)
  assert.match(items[1].resultPreview, /SQL 执行失败/)
})
