import test from 'node:test'
import assert from 'node:assert/strict'
import {
  canRerun,
  consumeEventPage,
  formatDuration,
  ingest,
  isQueued,
  EVAL_SKIP_EVENTS,
  lightenItem,
  modelOptions,
  normalizeEvalSettings,
  persistableValues,
  rebuildItems,
  recommendedAnswers,
  stampResult,
  statusLabel,
} from '../src/eval/format.js'

test('modelOptions uses the selected thinking switch and ignores sheet names', () => {
  assert.deepEqual(
    modelOptions({ model: '', thinking: 'on', thinkingLevel: 'medium' }),
    { use_memory: false, thinking: 'on', thinking_level: 'medium' },
  )
  assert.deepEqual(
    modelOptions({ model: '', thinking: 'off' }),
    { use_memory: false, thinking: 'off' },
  )
  assert.deepEqual(
    modelOptions({ model: 'm1', thinking: 'default' }),
    { use_memory: false, model_config_id: 'm1' },
  )
})

test('rebuildItems keeps finished rows and slices by index', () => {
  const workbook = {
    sheets: [{
      name: '思考模式',
      headers: ['问题'],
      rows: [
        { row: 2, values: { 问题: '一', 问题分类: 'A' } },
        { row: 3, values: { 问题: '二', 问题分类: 'B' } },
        { row: 4, values: { 问题: '三', 问题分类: 'C' } },
      ],
    }],
  }
  const previous = [{
    id: '思考模式:3',
    status: 'done',
    answer: '42',
    values: { 最终结果: '42' },
  }]
  const items = rebuildItems({
    workbook,
    selectedSheetNames: ['思考模式'],
    fromIndex: 2,
    toIndex: 3,
    previousItems: previous,
  })
  assert.equal(items.length, 2)
  assert.equal(items[0].question, '二')
  assert.equal(items[0].status, 'done')
  assert.equal(items[0].answer, '42')
  assert.equal(items[1].question, '三')
  assert.equal(items[1].status, 'queued')
})

test('recommendedAnswers prefer the recommended choice', () => {
  const { answers, records } = recommendedAnswers([{
    question_id: 'q1',
    prompt: '哪个产品？',
    choices: [
      { id: 'a', label: '全产品线', recommended: true },
      { id: 'b', label: '泰瑞沙' },
    ],
  }])
  assert.equal(answers[0].choice_id, 'a')
  assert.match(records[0], /全产品线/)
  assert.match(records[0], /推荐/)
})

test('eval catch-up skips token-stream noise', () => {
  assert.equal(EVAL_SKIP_EVENTS.has('agent.think.delta'), true)
  assert.equal(EVAL_SKIP_EVENTS.has('agent.content.delta'), true)
  assert.equal(EVAL_SKIP_EVENTS.has('tool.call'), false)
})

test('ingest captures sql, labs, clarification and the final answer', () => {
  const collected = { sqls: [], labs: [], clarifications: [], answer: '', status: 'running', error: '' }
  ingest(collected, 'tool.call', { name: 'query_db', call_id: 'c1', arguments: { sql: 'SELECT 1' } })
  ingest(collected, 'tool.result', { name: 'query_db', call_id: 'c1', ok: true, preview: { sql: 'SELECT 1' } })
  ingest(collected, 'ask_user.opened', { case_id: 'case-1', groups: [] })
  ingest(collected, 'agent.done', { answer: '完成' })
  assert.equal(collected.sqls[0].sql, 'SELECT 1')
  assert.equal(collected.status, 'done')
  assert.equal(collected.answer, '完成')
  assert.equal(collected.pendingClarify.case_id, 'case-1')
})

test('ingest captures bailian recall query and lab_type', () => {
  const collected = { sqls: [], labs: [], recalls: [], clarifications: [], answer: '', status: 'running', error: '' }
  ingest(collected, 'tool.call', {
    name: 'bailian_recall',
    call_id: 'c2',
    arguments: { query: '院外', lab_type: 'actual' },
  })
  ingest(collected, 'tool.result', {
    name: 'bailian_recall',
    call_id: 'c2',
    ok: true,
    preview: { query: '院外', lab_type: 'actual', text: '知识词条：院外' },
  })
  assert.equal(collected.recalls[0].query, '院外')
  assert.equal(collected.recalls[0].lab_type, 'actual')
  assert.match(collected.recalls[0].text, /院外/)
})

test('normalizeEvalSettings reads the old html sheet checkbox format', () => {
  const settings = normalizeEvalSettings({
    thinking: 'on',
    sheets: [
      { name: '思考模式', checked: true },
      { name: '非思考模式', checked: false },
    ],
  })
  assert.deepEqual(settings.selectedSheets, ['思考模式'])
  assert.equal(settings.thinking, 'on')
})

test('lightenItem drops heavy fields after a row is persisted', () => {
  const item = {
    status: 'done',
    answer: '很长的答案',
    sql: 'SELECT 1',
    labs: '实验室',
    clarify: '澄清',
    error: '',
    values: { 最终sql: 'SELECT 1', 最终结果: '很长的答案' },
  }
  lightenItem(item, '很长的答案')
  assert.equal(item.sql, '')
  assert.equal(item.labs, '')
  assert.equal(item.clarify, '')
  assert.equal(item.answer, '很长的答案')
  assert.equal(item.values['最终sql'], '')
})

test('status helpers', () => {
  assert.equal(statusLabel('queued'), '待跑')
  assert.equal(canRerun({ question: 'x', status: 'failed' }), true)
  assert.equal(canRerun({ question: 'x', status: 'running' }), false)
  assert.equal(isQueued({ status: 'queued' }), true)
  assert.equal(isQueued({ status: 'failed' }), false)
  assert.equal(formatDuration(1000), '1秒')
  assert.equal(formatDuration(125000), '2分05秒（125s）')
})

test('ingest ignores replayed tool.call events with the same call_id', () => {
  const collected = { sqls: [], labs: [], clarifications: [], answer: '', status: 'running', error: '' }
  const call = { name: 'query_db', call_id: 'c1', arguments: { sql: 'SELECT 1' } }
  const lab = { name: 'ask_lab', call_id: 'l1', arguments: { lab_id: 'actual', question: '销量' } }
  ingest(collected, 'tool.call', call)
  ingest(collected, 'tool.call', call)
  ingest(collected, 'tool.result', { name: 'query_db', call_id: 'c1', ok: true, preview: { sql: 'SELECT 1' } })
  ingest(collected, 'tool.call', lab)
  ingest(collected, 'tool.call', lab)
  ingest(collected, 'tool.result', {
    name: 'ask_lab',
    call_id: 'l1',
    ok: true,
    preview: { lab_id: 'actual', lab_session_id: 'sess-1' },
  })
  assert.equal(collected.sqls.length, 1)
  assert.equal(collected.labs.length, 1)
  assert.equal(collected.labs[0].session_id, 'sess-1')
})

test('consumeEventPage advances cursor even when the last page has no more events', () => {
  const collected = { sqls: [], labs: [], clarifications: [], answer: '', status: 'running', error: '' }
  const page = {
    items: [
      {
        type: 'tool.call',
        cursor: 7,
        payload: { name: 'query_db', call_id: 'c1', arguments: { sql: 'SELECT 1' } },
      },
    ],
    next_cursor: 7,
    has_more: false,
  }
  let cursor = consumeEventPage(collected, 0, page)
  assert.equal(cursor, 7)
  assert.equal(collected.sqls.length, 1)
  cursor = consumeEventPage(collected, cursor, { items: [], next_cursor: 7, has_more: false })
  assert.equal(cursor, 7)
  consumeEventPage(collected, 0, page)
  assert.equal(collected.sqls.length, 1)
})

test('stampResult and persistableValues keep SQL off the extra values payload', () => {
  const item = {
    values: { 问题: '销量', 问题分类: '优化' },
    runId: 'run-1',
    duration: '8秒',
  }
  stampResult(item, {
    status: 'done',
    answer: '42',
    error: '',
    clarifications: [],
    sqls: [{ sql: 'SELECT 1', ok: true, call_id: 'c1' }],
    labs: [{ lab_id: 'actual', session_id: 's1', question: '销量' }],
    recalls: [],
  })
  assert.match(item.sql, /SELECT 1/)
  assert.match(item.labs, /actual/)
  const extra = persistableValues(item)
  assert.equal(extra['最终sql'], undefined)
  assert.equal(extra['实验室选择'], undefined)
  assert.equal(extra['最终结果'], undefined)
  assert.equal(extra['问题'], '销量')
})
