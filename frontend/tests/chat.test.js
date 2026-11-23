import test from 'node:test'
import assert from 'node:assert/strict'
import { currentModelOptions, handleEvent, resumeLiveRun } from '../src/chat.js'
import { store } from '../src/store.js'

function blank() {
  return {
    status: 'starting',
    startedAt: 0,
    lastCursor: '',
    thinking: { open: true, streaming: false, text: '' },
    steps: [],
    ledger: [],
    clarify: null,
    clarifyHistory: [],
    answer: { md: '', done: false, streaming: false, draft: '', usage: null, finishReason: '' },
    failure: '',
  }
}

test('analysis cards retain their own KPIs and event references through replay', () => {
  const message = blank()
  const payload = { version: 2, title: '总体', kpis: [{ label: '金额', value: 100, unit: '元' }],
    data: { columns: ['城市', '金额'], rows: [['北京', 100]] },
    details: { columns: ['城市', '金额'], rows: [['北京', 100]] },
    charts: [{ type: 'combo', label: '复合图', option: { series: [] } }] }
  handleEvent(message, { id: '10', type: 'chart.ready', payload })
  handleEvent(message, { id: '20', type: 'chart.ready', payload: { ...payload, title: '下钻', kpis: [{ label: '金额', value: 20 }] } })
  assert.equal(message.chartCards.length, 2)
  assert.equal(message.chartCards[0].kpis[0].value, 100)
  assert.equal(message.chartCards[1].kpis[0].value, 20)
  assert.deepEqual(message.chartCards.map(card => card.event_cursor), [10, 20])
  handleEvent(message, { id: '10', type: 'chart.ready', payload })
  assert.deepEqual(message.chartCards.map(card => card.event_cursor), [10, 20])
  payload.data.rows[0][1] = 999
  assert.equal(message.chartCards[0].data.rows[0][1], 100)
})

test('durable job failures show a readable error and stop the spinner', () => {
  const message = blank()
  message.thinking.streaming = true
  message.answer.streaming = true
  handleEvent(message, { id: '12', type: 'job.failed', payload: { code: 'JOB_VALUEERROR' } })
  handleEvent(message, { id: '13', type: 'quick.failed', payload: {
    code: 'JOB_VALUEERROR', message: 'Durable Quick job failed closed',
  } })
  assert.equal(message.status, 'failed')
  assert.match(message.answer.md, /后台分析失败/)
  assert.match(message.answer.md, /JOB_VALUEERROR/)
  assert.equal(message.answer.done, true)
  assert.equal(message.answer.streaming, false)
  assert.equal(message.thinking.streaming, false)
})

test('model options reflect composer choices', () => {
  const saved = { modelChoice: store.modelChoice, thinking: store.thinking, thinkingLevel: store.thinkingLevel }
  try {
    store.modelChoice = ''; store.thinking = 'default'
    assert.deepEqual(currentModelOptions(), {})

    store.modelChoice = 'model-2'; store.thinking = 'on'; store.thinkingLevel = 'high'
    assert.deepEqual(currentModelOptions(), {
      model_config_id: 'model-2', thinking: 'on', thinking_level: 'high',
    })

    store.thinking = 'off'
    assert.deepEqual(currentModelOptions(), { model_config_id: 'model-2', thinking: 'off' })
  } finally {
    Object.assign(store, saved)
  }
})

test('event cursor is tracked for resumption', () => {
  const message = blank()
  handleEvent(message, { id: '7', type: 'run.created', payload: { status: 'received' } })
  assert.equal(message.lastCursor, '7')
  assert.equal(message.status, 'received')
})

test('ledger snapshots replace the previous progress ledger', () => {
  const message = blank()
  handleEvent(message, {
    id: '1',
    type: 'agent.ledger.updated',
    payload: { entries: [{ step: 0, kind: 'scope', text: '只查重点民营机构' }] },
  })
  assert.equal(message.ledger.length, 1)
  handleEvent(message, {
    id: '2',
    type: 'agent.ledger.updated',
    payload: {
      entries: [
        { step: 0, kind: 'scope', text: '只查重点民营机构' },
        { step: 2, kind: 'fact', text: '查询成功，共 3 行' },
      ],
    },
  })
  assert.equal(message.ledger.length, 2)
  assert.equal(message.ledger[1].kind, 'fact')
  handleEvent(message, { id: '3', type: 'agent.ledger.updated', payload: {} })
  assert.deepEqual(message.ledger, [])
})

test('step events group thinking and content by step number', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, { id: '2', type: 'agent.think.delta', payload: { step: 1, text: '先查' } })
  handleEvent(message, { id: '3', type: 'agent.think.delta', payload: { step: 1, text: '达成率' } })
  assert.equal(message.steps.length, 1)
  assert.equal(message.steps[0].thinking.text, '先查达成率')
  assert.equal(message.steps[0].thinking.streaming, true)

  handleEvent(message, {
    id: '4',
    type: 'assistant.message',
    payload: { step: 1, content: '', reasoning: '先查达成率', tool_calls: [{ id: 'c1' }], usage: { total_tokens: 5 } },
  })
  assert.equal(message.steps[0].thinking.streaming, false)
  assert.equal(message.answer.md, '')
})

test('a new step start collapses every earlier step', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, { id: '2', type: 'agent.think.delta', payload: { step: 1, text: '先查' } })
  assert.equal(message.steps[0].open, true)

  handleEvent(message, { id: '3', type: 'agent.step_start', payload: { step: 2 } })
  assert.equal(message.steps[0].open, false, 'step 1 must collapse once step 2 lands')
  assert.equal(message.steps[1].open, true, 'the fresh step stays open')

  // Manual re-expand survives until the next step arrives.
  message.steps[0].open = true
  handleEvent(message, { id: '4', type: 'agent.step_start', payload: { step: 3 } })
  assert.equal(message.steps[0].open, false)
  assert.equal(message.steps[1].open, false)
  assert.equal(message.steps[2].open, true)
})

test('content deltas stream into the draft until the final message lands', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, { id: '2', type: 'agent.content.delta', payload: { step: 1, text: '达成率 ' } })
  handleEvent(message, { id: '3', type: 'agent.content.delta', payload: { step: 1, text: '116.5%' } })
  assert.equal(message.answer.streaming, true)
  assert.equal(message.answer.draft, '达成率 116.5%')

  handleEvent(message, {
    id: '4',
    type: 'assistant.message',
    payload: { step: 1, content: '达成率 116.5%', reasoning: '', tool_calls: [], finish_reason: 'stop', usage: { total_tokens: 9 } },
  })
  assert.equal(message.answer.md, '达成率 116.5%')
  assert.equal(message.answer.streaming, false)
  assert.equal(message.answer.draft, '')
  assert.equal(message.answer.finishReason, 'stop')
})

test('intermediate narration with tool calls never reaches the answer card', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, { id: '2', type: 'agent.content.delta', payload: { step: 1, text: '让我分步来：先查省份' } })
  assert.equal(message.answer.draft, '让我分步来：先查省份')

  handleEvent(message, {
    id: '3',
    type: 'assistant.message',
    payload: { step: 1, content: '让我分步来：先查省份', reasoning: '', tool_calls: [{ call_id: 'c1', name: 'ask_lab' }] },
  })
  assert.equal(message.steps[0].content, '让我分步来：先查省份')
  assert.equal(message.answer.draft, '', 'draft must be cleared once the turn keeps calling tools')
  assert.equal(message.answer.md, '', 'only the final toolless summary may fill the answer card')
  assert.equal(message.answer.streaming, false)
})

test('nested sub-agent events attach under the parent tool call', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, {
    id: '2',
    type: 'tool.call',
    payload: { call_id: 'delegate-1', name: 'agent_lab_sql', step: 1, kind: 'agent', arguments: { question: '销量' } },
  })
  handleEvent(message, {
    id: '3',
    type: 'agent.step_start',
    payload: { step: 1, parent_call_id: 'delegate-1', agent_name: '实验室智能体' },
  })
  handleEvent(message, {
    id: '4',
    type: 'agent.think.delta',
    payload: { step: 1, text: '先核对口径', parent_call_id: 'delegate-1' },
  })
  handleEvent(message, {
    id: '5',
    type: 'tool.call',
    payload: {
      call_id: 'lab-1',
      name: 'ask_lab',
      step: 1,
      arguments: { question: '销量', lab_id: 'actual' },
      parent_call_id: 'delegate-1',
    },
  })
  handleEvent(message, {
    id: '6',
    type: 'agent.done',
    payload: { answer: 'SELECT 1', parent_call_id: 'delegate-1', agent_name: '实验室智能体' },
  })
  const tool = message.steps[0].tools[0]
  assert.equal(tool.kind, 'agent')
  assert.equal(tool.child.agentName, '实验室智能体')
  assert.equal(tool.child.steps[0].thinking.text, '先核对口径')
  assert.equal(tool.child.steps[0].tools[0].name, 'ask_lab')
  assert.equal(tool.child.status, 'done')
  assert.equal(tool.child.answer.md, 'SELECT 1')
  assert.equal(message.status, 'running')
  assert.equal(message.lastCursor, '6')
})

test('clarification suspension clears any in-flight answer draft', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, { id: '2', type: 'agent.content.delta', payload: { step: 1, text: '过程旁白' } })
  handleEvent(message, {
    id: '3',
    type: 'ask_user.opened',
    payload: {
      case_id: 'case-9',
      groups: [
        { question_id: 'q1', prompt: '口径？', choices: [{ id: 'a', label: '全部机构' }, { id: 'b', label: '仅医院' }] },
      ],
    },
  })
  assert.equal(message.answer.draft, '')
  assert.equal(message.answer.streaming, false)
  assert.equal(message.status, 'waiting_clarification')
})

test('resumeLiveRun does not steal the composer of another session', async () => {
  store.sessionId = 'session-b'
  store.activeController = null
  store.busy = false
  const message = {
    ...blank(),
    sessionId: 'session-a',
    eventsUrl: '/api/v2/runs/run-a/stream',
    runId: 'run-a',
    status: 'running',
  }
  await resumeLiveRun(message)
  assert.equal(store.busy, false)
  assert.equal(store.activeController, null)
  store.sessionId = ''
})

test('tool calls attach to their step and resolve with the result', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, {
    id: '2',
    type: 'tool.call',
    payload: { step: 1, call_id: 'call-1', name: 'ask_lab', arguments: { lab_id: 'actual', question: '今年销量' } },
  })
  const [tool] = message.steps[0].tools
  assert.equal(tool.label, '实验室')
  assert.equal(tool.state, 'running')
  assert.match(tool.summary, /吉利德 DDI/)

  handleEvent(message, {
    id: '3',
    type: 'tool.result',
    payload: { call_id: 'call-1', ok: true, output: '候选 SQL 已生成', preview: { columns: ['v'], rows: [[1]] } },
  })
  assert.equal(tool.state, 'done')
  assert.equal(tool.ok, true)
  assert.equal(tool.output, '候选 SQL 已生成')
  assert.deepEqual(tool.preview.columns, ['v'])
})

test('failed tool results keep the error output visible', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, {
    id: '2',
    type: 'tool.call',
    payload: { step: 1, call_id: 'call-2', name: 'query_db', arguments: { sql: 'SELECT 1' } },
  })
  handleEvent(message, { id: '3', type: 'tool.result', payload: { call_id: 'call-2', ok: false, output: 'SQL 被拒绝' } })
  const [tool] = message.steps[0].tools
  assert.equal(tool.ok, false)
  assert.equal(tool.output, 'SQL 被拒绝')
  assert.equal(tool.label, '数据库查询')
})

test('export_xlsx is labelled for download', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.step_start', payload: { step: 1 } })
  handleEvent(message, {
    id: '2',
    type: 'tool.call',
    payload: {
      step: 1,
      call_id: 'call-3',
      name: 'export_xlsx',
      arguments: { title: '泰瑞沙 2025 YTD', summary: '共 462 行' },
    },
  })
  handleEvent(message, {
    id: '3',
    type: 'tool.result',
    payload: {
      call_id: 'call-3',
      ok: true,
      output: '已导出完整结果',
      preview: {
        filename: '泰瑞沙 2025 YTD.xlsx',
        row_count: 462,
        download_path: '/api/v2/runs/run-1/exports/artifact_1',
      },
    },
  })
  const [tool] = message.steps[0].tools
  assert.equal(tool.label, 'xlsx导出')
  assert.match(tool.summary, /泰瑞沙 2025 YTD/)
  assert.equal(tool.preview.row_count, 462)
  assert.equal(tool.preview.download_path, '/api/v2/runs/run-1/exports/artifact_1')
})

test('ask_user opens a clarification card and parks the run', () => {
  const message = blank()
  handleEvent(message, {
    id: '1',
    type: 'ask_user.opened',
    payload: {
      case_id: 'case-1',
      run_id: 'run-1',
      groups: [
        {
          question_id: 'domain',
          prompt: '属于哪个数据域？',
          choices: [
            { choice_id: 'actual', label: 'Actual 实际销售' },
            { choice_id: 'demand', label: 'Demand' },
          ],
        },
      ],
    },
  })
  assert.equal(message.status, 'waiting_clarification')
  assert.ok(message.clarify)
  assert.equal(message.clarify.caseId, 'case-1')

  handleEvent(message, { id: '2', type: 'ask_user.answered', payload: { case_id: 'case-1', answer: 'Actual 实际销售' } })
  assert.equal(message.status, 'running')
  assert.equal(message.clarify.confirmed, 'Actual 实际销售')
})

test('a second ask_user opens a new card and keeps the first confirmation', () => {
  const message = blank()
  handleEvent(message, {
    id: '1',
    type: 'ask_user.opened',
    payload: {
      case_id: 'case-1',
      groups: [{ question_id: 'metric', prompt: '查什么？', choices: [{ id: 'amount', label: '销售金额' }] }],
    },
  })
  handleEvent(message, { id: '2', type: 'ask_user.answered', payload: { case_id: 'case-1', answer: '销售金额' } })
  handleEvent(message, { id: '3', type: 'memory.auto_saved', payload: { case_id: 'case-1', entry_id: 'mem-1' } })
  assert.equal(message.clarify.confirmed, '销售金额')
  assert.equal(message.clarify.memorySaved, true)

  handleEvent(message, {
    id: '4',
    type: 'ask_user.opened',
    payload: {
      case_id: 'case-2',
      groups: [{
        question_id: 'rc',
        prompt: '您所在的RC是哪一个？',
        choices: [
          { id: 'east', label: 'CVRM东一区' },
          { id: 'west', label: 'CVRM西区' },
        ],
      }],
    },
  })
  assert.equal(message.status, 'waiting_clarification')
  assert.equal(message.clarify.caseId, 'case-2')
  assert.equal(message.clarify.confirmed, '')
  assert.equal(message.clarify.groups[0].prompt, '您所在的RC是哪一个？')
  assert.equal(message.clarifyHistory.length, 1)
  assert.equal(message.clarifyHistory[0].caseId, 'case-1')
  assert.equal(message.clarifyHistory[0].confirmed, '销售金额')
  assert.equal(message.clarifyHistory[0].memorySaved, true)
})

test('a late first-case answer does not confirm the second clarification card', () => {
  const message = blank()
  handleEvent(message, {
    id: '1',
    type: 'ask_user.opened',
    payload: {
      case_id: 'case-2',
      groups: [{ question_id: 'rc', prompt: '您所在的RC是哪一个？', choices: [{ id: 'east', label: 'CVRM东一区' }] }],
    },
  })
  handleEvent(message, { id: '2', type: 'ask_user.answered', payload: { case_id: 'case-1', answer: '销售金额' } })
  assert.equal(message.clarify.caseId, 'case-2')
  assert.equal(message.clarify.confirmed, '')
})

test('agent.done finalizes the answer card', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.done', payload: { answer: '最终答案' } })
  assert.equal(message.answer.md, '最终答案')
  assert.equal(message.answer.done, true)
  assert.equal(message.status, 'done')
})

test('agent.failed surfaces the failure message', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'agent.failed', payload: { code: 'NO_ACTIVE_MODEL', message: '没有激活的模型配置' } })
  assert.equal(message.status, 'failed')
  assert.equal(message.failure, '没有激活的模型配置')
  assert.equal(message.answer.done, true)
})

test('quick.failed without an answer falls back to a prose notice', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'quick.failed', payload: { code: 'JOB_TIMEOUT' } })
  assert.equal(message.status, 'failed')
  assert.match(message.answer.md, /JOB_TIMEOUT/)
})

test('quick.done without an answer keeps the failed notice instead of blanking it', () => {
  const message = blank()
  handleEvent(message, { id: '1', type: 'quick.done', payload: { status: 'failed' } })
  assert.equal(message.status, 'failed')
  assert.match(message.answer.md, /未能生成答案/)
})
