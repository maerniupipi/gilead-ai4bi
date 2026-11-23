export const RESULT_HEADERS = ['澄清选项', '最终sql', '实验室选择', '百炼召回', '最终结果', '持续时间']
export const EXTRA_HEADERS = ['状态', '运行ID']
export const TERMINAL = new Set(['partial', 'completed', 'failed', 'cancelled', 'done'])
export const EVAL_SKIP_EVENTS = new Set(['agent.think.delta', 'agent.content.delta'])
export const EVAL_EVENT_PAGE_SIZE = 1000

export const STATUS_LABEL = {
  queued: '待跑',
  running: '进行中',
  clarify: '澄清中',
  done: '完成',
  failed: '失败',
  paused: '暂停',
}

export function statusLabel(status) {
  return STATUS_LABEL[status] || status
}

export function canRerun(item) {
  return Boolean(item?.question) && item.status !== 'running' && item.status !== 'clarify'
}

export function isQueued(item) {
  return item?.status === 'queued' || item?.status === 'paused'
}

export function modelOptions(settings) {
  const options = { use_memory: false }
  if (settings.model) options.model_config_id = settings.model
  const thinking = settings.thinking
  if (thinking && thinking !== 'default') {
    options.thinking = thinking
    if (thinking === 'on') options.thinking_level = settings.thinkingLevel || 'medium'
  }
  return options
}

export function concurrencyOf(value) {
  return Math.min(8, Math.max(1, Number(value) || 4))
}

export function normalizeEvalSettings(saved = {}) {
  const selectedSheets = Array.isArray(saved.selectedSheets) && saved.selectedSheets.length
    ? saved.selectedSheets.map(String)
    : Array.isArray(saved.sheets)
      ? saved.sheets.filter((sheet) => sheet && sheet.checked !== false).map((sheet) => sheet.name).filter(Boolean)
      : []
  return {
    model: saved.model || '',
    thinking: saved.thinking || 'default',
    thinkingLevel: saved.thinkingLevel || 'medium',
    fromIndex: saved.fromIndex ?? 1,
    toIndex: saved.toIndex ?? '',
    concurrency: saved.concurrency ?? 4,
    selectedSheets,
  }
}

export function previewText(value, limit = 160) {
  const text = String(value || '')
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}…`
}

export function rebuildItems({ workbook, selectedSheetNames, fromIndex, toIndex, previousItems = [] }) {
  const from = Math.max(1, Number(fromIndex) || 1)
  const toRaw = Number(toIndex)
  const to = toRaw > 0 ? toRaw : Infinity
  const previous = Object.fromEntries(previousItems.map((item) => [item.id, item]))
  const picked = new Set(selectedSheetNames)
  const items = []
  for (const sheet of workbook?.sheets || []) {
    if (!picked.has(sheet.name)) continue
    sheet.rows.forEach((row, index) => {
      const n = index + 1
      if (n < from || n > to) return
      const id = `${sheet.name}:${row.row}`
      const prior = previous[id]
      if (prior && (prior.status === 'done' || prior.status === 'failed')) {
        items.push({
          ...prior,
          id,
          sheet: sheet.name,
          headers: sheet.headers,
          row: row.row,
          index: n,
          values: { ...(prior.values || {}) },
          question: prior.question || String(row.values?.['问题'] || '').trim(),
          category: prior.category || row.values?.['问题分类'] || '',
        })
        return
      }
      items.push({
        id,
        sheet: sheet.name,
        headers: sheet.headers,
        row: row.row,
        index: n,
        values: { ...(row.values || {}) },
        question: String(row.values?.['问题'] || '').trim(),
        category: row.values?.['问题分类'] || '',
        status: 'queued',
        clarify: '',
        sql: '',
        labs: '',
        recalls: '',
        answer: '',
        duration: '',
        runId: '',
        error: '',
      })
    })
  }
  return items
}

export function formatClarifications(records) {
  return records.join('\n\n-----\n\n')
}

export function formatSqls(sqls) {
  return sqls.map((item, index) => {
    const mark = index === sqls.length - 1 ? '（最终查询）' : ''
    const ok = item.ok === false ? '（执行失败）' : ''
    return `===== SQL ${index + 1}${mark}${ok} =====\n${item.sql || ''}`.trim()
  }).join('\n\n')
}

export function formatLabs(labs) {
  return labs.map((item, index) => [
    `===== 实验室 ${index + 1} =====`,
    `实验室：${item.lab_id || ''}`,
    `session_id：${item.session_id || ''}`,
    item.question ? `问题：${item.question}` : '',
  ].filter(Boolean).join('\n')).join('\n\n')
}

export function formatRecalls(recalls) {
  return (recalls || []).map((item, index) => [
    `===== 百炼 ${index + 1} =====`,
    `lab_type：${item.lab_type || ''}`,
    item.query ? `query：${item.query}` : '',
    item.text ? `召回：${item.text}` : '',
  ].filter(Boolean).join('\n')).join('\n\n')
}

export function formatDuration(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(seconds / 60)
  const remain = seconds % 60
  if (minutes <= 0) return `${seconds}秒`
  return `${minutes}分${String(remain).padStart(2, '0')}秒（${seconds}s）`
}

export function recommendedAnswers(groups) {
  const answers = []
  const records = []
  for (const group of groups || []) {
    const choices = group.choices || group.options || []
    const recommended = choices.filter((choice) => choice.recommended)
    const picked = recommended.length ? recommended : (choices[0] ? [choices[0]] : [])
    const labels = picked.map((choice) => choice.label).filter(Boolean)
    const record = `问：${group.prompt || group.question || ''}\n答：${labels.join('、') || '按推荐理解继续'}${recommended.length ? '（推荐）' : ''}`
    records.push(record)
    if (group.multi_select || group.multiSelect) {
      answers.push({
        question_id: group.question_id || group.questionId,
        choice_ids: picked.map((choice) => choice.id || choice.choice_id || choice.label),
      })
    } else if (picked[0]) {
      answers.push({
        question_id: group.question_id || group.questionId,
        choice_id: picked[0].id || picked[0].choice_id || picked[0].label,
      })
    } else {
      answers.push({
        question_id: group.question_id || group.questionId,
        free_text: '按推荐理解继续',
      })
    }
  }
  return { answers, records }
}

export function nextEventCursor(after, page) {
  const cursor = Number(after || 0)
  const items = page?.items || []
  if (!items.length) return cursor
  const next = Number(page.next_cursor ?? items[items.length - 1].cursor)
  if (!Number.isFinite(next) || next <= cursor) return cursor
  return next
}

export function ingestEvents(collected, events) {
  for (const event of events || []) {
    if (!event || EVAL_SKIP_EVENTS.has(event.type)) continue
    ingest(collected, event.type, event.payload || {})
  }
  return collected
}

export function consumeEventPage(collected, after, page) {
  ingestEvents(collected, page?.items || [])
  return nextEventCursor(after, page)
}

export function persistableValues(item) {
  const values = { ...(item?.values || {}) }
  for (const key of [...RESULT_HEADERS, ...EXTRA_HEADERS]) delete values[key]
  return values
}

export function ingest(collected, type, payload) {
  payload = payload || {}
  if (type === 'run.status_changed') collected.status = payload.to || collected.status
  if (type === 'tool.call') {
    const callId = payload.call_id
    if (callId) {
      collected.seenCallIds = collected.seenCallIds || new Set()
      if (collected.seenCallIds.has(callId)) return collected
      collected.seenCallIds.add(callId)
    }
    if (payload.name === 'query_db') {
      collected.sqls.push({ sql: payload.arguments?.sql || '', ok: null, call_id: payload.call_id })
    }
    if (payload.name === 'ask_lab') {
      collected.labs.push({
        lab_id: payload.arguments?.lab_id || '',
        question: payload.arguments?.question || '',
        session_id: '',
        call_id: payload.call_id,
      })
    }
    if (payload.name === 'bailian_recall' || payload.name === 'field_recall' || payload.name === 'value_recall') {
      collected.recalls = collected.recalls || []
      collected.recalls.push({
        query: payload.arguments?.query || '',
        lab_type: payload.arguments?.lab_type || '',
        text: '',
        call_id: payload.call_id,
      })
    }
  }
  if (type === 'tool.result') {
    if (payload.name === 'query_db') {
      const row = collected.sqls.find((item) => item.call_id === payload.call_id) || collected.sqls[collected.sqls.length - 1]
      if (row) {
        row.ok = Boolean(payload.ok)
        if (payload.preview?.sql) row.sql = payload.preview.sql
      } else if (payload.preview?.sql) {
        collected.sqls.push({ sql: payload.preview.sql, ok: Boolean(payload.ok), call_id: payload.call_id })
      }
    }
    if (payload.name === 'ask_lab') {
      const row = collected.labs.find((item) => item.call_id === payload.call_id) || collected.labs[collected.labs.length - 1]
      if (row) {
        row.session_id = payload.preview?.lab_session_id || row.session_id
        row.lab_id = payload.preview?.lab_id || row.lab_id
      }
    }
    if (payload.name === 'bailian_recall' || payload.name === 'field_recall' || payload.name === 'value_recall') {
      collected.recalls = collected.recalls || []
      const row = collected.recalls.find((item) => item.call_id === payload.call_id) || collected.recalls[collected.recalls.length - 1]
      if (row) {
        row.text = payload.preview?.text || row.text
        row.query = payload.preview?.query || row.query
        row.lab_type = payload.preview?.lab_type || row.lab_type
      }
    }
  }
  if (type === 'ask_user.opened') {
    collected.status = 'waiting_clarification'
    collected.pendingClarify = payload
  }
  if (type === 'assistant.message' && payload.content && !(payload.tool_calls || []).length) {
    collected.answer = payload.content
  }
  if (type === 'agent.done') {
    collected.answer = payload.answer || collected.answer
    collected.status = 'done'
  }
  if (type === 'agent.failed' || type === 'quick.failed') {
    collected.status = 'failed'
    collected.error = payload.message || payload.code || '分析失败'
  }
  if (type === 'quick.done') collected.status = payload.status || collected.status
  return collected
}

export function stampResult(item, collected) {
  item.status = collected.status === 'failed' ? 'failed' : 'done'
  item.answer = collected.answer || ''
  item.error = collected.error || ''
  item.clarify = formatClarifications(collected.clarifications || [])
  item.sql = formatSqls(collected.sqls || [])
  item.labs = formatLabs(collected.labs || [])
  item.recalls = formatRecalls(collected.recalls || [])
  item.values['澄清选项'] = item.clarify
  item.values['最终sql'] = item.sql
  item.values['实验室选择'] = item.labs
  item.values['百炼召回'] = item.recalls
  item.values['最终结果'] = item.answer || item.error
  item.values['持续时间'] = item.duration
  item.values['状态'] = statusLabel(item.status)
  item.values['运行ID'] = item.runId
  return item
}

export function exportSheets(items) {
  const bySheet = new Map()
  for (const item of items) {
    if (!bySheet.has(item.sheet)) {
      const headers = [...(item.headers || [])]
      for (const extra of [...RESULT_HEADERS, ...EXTRA_HEADERS]) {
        if (!headers.includes(extra)) headers.push(extra)
      }
      bySheet.set(item.sheet, { name: item.sheet, headers, rows: [] })
    }
    bySheet.get(item.sheet).rows.push({ row: item.row, values: item.values })
  }
  return [...bySheet.values()]
}

export function lightenItem(item, preview = '') {
  item.clarify = ''
  item.sql = ''
  item.labs = ''
  item.recalls = ''
  item.answer = preview || item.error || (item.status === 'done' ? '已落库' : '')
  if (item.values) {
    item.values['澄清选项'] = ''
    item.values['最终sql'] = ''
    item.values['实验室选择'] = ''
    item.values['百炼召回'] = ''
    item.values['最终结果'] = item.answer
  }
  return item
}

export function summaryToPrior(summary) {
  return {
    id: `${summary.sheet}:${summary.row}`,
    sheet: summary.sheet,
    row: summary.row,
    question: summary.question || '',
    category: summary.category || '',
    status: summary.status || 'queued',
    duration: summary.duration || '',
    runId: summary.run_id || '',
    error: summary.error || '',
    answer: summary.answer_preview || '',
    clarify: '',
    sql: '',
    labs: '',
    recalls: '',
    headers: summary.headers || [],
    values: {},
  }
}

export function clearItemResult(item) {
  item.status = 'queued'
  item.error = ''
  item.answer = ''
  item.clarify = ''
  item.sql = ''
  item.labs = ''
  item.recalls = ''
  item.duration = ''
  item.runId = ''
  item.values['澄清选项'] = ''
  item.values['最终sql'] = ''
  item.values['实验室选择'] = ''
  item.values['百炼召回'] = ''
  item.values['最终结果'] = ''
  item.values['持续时间'] = ''
  item.values['状态'] = statusLabel('queued')
  item.values['运行ID'] = ''
  return item
}
