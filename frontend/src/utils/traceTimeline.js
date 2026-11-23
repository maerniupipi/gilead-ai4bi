/** Project a raw run event stream into a readable session log. */

import { labDisplayName, rewriteLabLabelsInText } from '../lib/labConnection.js'

export const ROLE_LABEL = {
  system: '系统',
  user: '用户',
  context: '上下文',
  assistant: '小吉',
  tool: '工具',
}

export function roleLabels(assistantName = '小吉') {
  return { ...ROLE_LABEL, assistant: assistantName || '小吉' }
}

export const TOOL_CATALOG = {
  recall_lab: {label:'召回实验室',description:'在已绑定的数据库中匹配字段、实际取值和别名。',parameters:{lab_id:{type:'string',description:'实验室组合'},question:{type:'string',description:'待匹配的数据库字段或取值'}}},
  ask_lab: {
    label: '实验室',
    description:
      '调用实验室：把一个原子化的查数问题交给指定实验室，产出候选 SQL 及其理解说明。返回的 SQL 是候选，必须再用数据库查询执行后才能作为事实。',
    parameters: {
      question: { type: 'string', description: '原子化问题：单一意图、包含产品/时间/口径等关键要素' },
      lab_id: { type: 'string', description: '目标实验室' },
      remark: { type: 'string', description: '可选：本次问题的补充备注' },
      attach_upstream: { type: 'boolean', description: '以上一跳已核验结果为过滤条件时为 true' },
    },
  },
  inspect_schema: {
    label: '表结构',
    description: '读取已勾选表的结构：表名、字段、类型、注释。',
    parameters: {
      tables: { type: 'array', description: '可选。只看这些表' },
    },
  },
  generate_sql: {
    label: '生成 SQL 实验室',
    description: '由平台为一个原子问题生成只读 SQL，返回可供本轮分析引用的编号。',
    parameters: {
      question: { type: 'string', description: '原子化查数问题' },
      lab_id: { type: 'string', description: '目标实验室，可选' },
      context: { type: 'string', description: '已召回的参考信息' },
    },
  },
  validate_sql: {
    label: 'SQL校验',
    description: '用 SQLGlot 校验一条 SELECT 的语法和字段。',
    parameters: {
      sql: { type: 'string', description: '待校验的只读 SELECT' },
    },
  },
  query_db: {
    label: '数据库查询',
    description: '对已配置的本地数据源执行一条只读 SELECT 语句，返回列与数据行。',
    parameters: {
      sql: { type: 'string', description: '一条完整的只读 SELECT 语句' },
    },
  },
  export_xlsx: {
    label: 'xlsx导出',
    description: '把最近一次成功的 query_db 完整结果集写成工作簿，并返回下载链接。超过 30 行的最终取数应调用本工具。',
    parameters: {
      title: { type: 'string', description: '这个问题是什么，写入工作簿第一行合并单元格' },
      summary: { type: 'string', description: '结果的简要说明，与 title 一起写入第一行' },
    },
  },
  knowledge_search: {
    label: '知识检索',
    description: '检索共享业务知识，返回文档、章节和原文摘录。',
    parameters: {
      query: { type: 'string', description: '检索词：指标名、产品名、口径描述等' },
    },
  },
  bailian_recall: {
    label: '百炼召回',
    description: '远程知识 API。未配置时自动改走本地字段/取值召回。',
    parameters: {
      query: { type: 'string', description: '用户原问题全文，或某个短词' },
      lab_type: { type: 'string', description: '对应实验室名称，与 ask_lab 的 lab_id 相同' },
    },
  },
  field_recall: {
    label: '字段召回',
    description: '把用户问题匹配到已勾选表的字段名和注释。',
    parameters: {
      query: { type: 'string', description: '用户原问题全文，或某个短词' },
      lab_type: { type: 'string', description: '对应实验室名称，可选' },
    },
  },
  value_recall: {
    label: '取值召回',
    description: '在已勾选表上探测字段取值。',
    parameters: {
      query: { type: 'string', description: '用户原问题全文，或某个短词' },
      table: { type: 'string', description: '可选。限定一张表' },
      column: { type: 'string', description: '可选。限定一个字段' },
    },
  },
  knowledge_read: {
    label: '知识阅读',
    description: '按知识检索返回的文档和章节阅读原文。',
    parameters: {
      document_id: { type: 'string', description: '文档编号' },
      section: { type: 'integer', description: '匹配章节' },
      offset: { type: 'integer', description: '长章节续读位置' },
    },
  },
  memory_save: {
    label: '记忆写入',
    description: '知识沉淀：把用户声明的默认口径、偏好或指标定义持久化为可复用知识。',
    parameters: {
      scope: { type: 'string', description: 'personal=仅该用户；review=提交共享审核' },
      content: { type: 'string', description: '完整口径描述' },
      category: { type: 'string', description: '个人记忆分类' },
      title: { type: 'string', description: '提交审核时的短标题' },
      target: { type: 'string', description: '审核通过后的去向' },
    },
  },
  ask_user: {
    label: '用户澄清',
    description: '向用户澄清：问题存在口径歧义或缺少关键信息时，提出 1–3 个问题并给出选项。',
    parameters: {
      questions: { type: 'array', description: '1–3 个澄清问题' },
      question: { type: 'string', description: '兼容写法：单个澄清问题' },
      options: { type: 'array', description: '兼容写法：2–4 个候选答案' },
      multi_select: { type: 'boolean', description: 'true=可多选' },
    },
  },
  update_ledger: {
    label: '更新台账',
    description: '更新进度台账：把对问题要素的理解记成一条，用户会实时看到。',
    parameters: {
      action: { type: 'string', description: 'update=新增或覆盖；delete=移除' },
      key: { type: 'string', description: '条目主体，同 key 会被覆盖' },
      kind: { type: 'string', description: 'term / constant / qualifier / formula / scope / time' },
      text: { type: 'string', description: '简短结论' },
    },
  },
  agent_lab_sql: {
    label: '实验室智能体',
    description: '把原子化查数问题交给实验室智能体，由它生成候选 SQL。',
    parameters: {
      question: { type: 'string', description: '原子化的查数问题' },
      lab_id: { type: 'string', description: '目标实验室' },
    },
  },
  agent_bailian: {
    label: '召回智能体',
    description: '把词条或原问题交给召回智能体，取得字段名与取值。',
    parameters: {
      query: { type: 'string', description: '原问题全文或短词' },
      lab_type: { type: 'string', description: '对应实验室名称' },
    },
  },
}

const SKIP_TYPES = new Set([
  'agent.think.delta',
  'agent.content.delta',
  'agent.step_start',
  'agent.step_end',
  'agent.turn_end',
  'job.enqueued',
  'job.claimed',
  'job.succeeded',
  'run.status_changed',
])

const LEDGER_KIND_LABEL = {
  term: '术语',
  constant: '常量',
  qualifier: '限定',
  formula: '公式',
  scope: '口径',
  time: '时间',
  fact: '事实',
  conclusion: '结论',
}

const MODEL_COLORS = ['#5b8def', '#2aa89c', '#7b6cf0', '#4c8dda', '#3aa38a', '#6d7be3']
const TOOL_COLOR = '#e3943a'
const TOOL_FAIL_COLOR = '#c45c4a'
const INPUT_COLOR = '#3a3a3c'
const CONTEXT_COLOR = '#8a96a3'

export function toolMeta(name) {
  const spec = TOOL_CATALOG[name]
  if (spec) return { name, ...spec }
  return {
    name,
    label: name || '工具',
    description: '该工具暂无内置说明。',
    parameters: {},
  }
}

export function oneLine(value, max = 140) {
  const text = String(value ?? '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`+/g, '')
    .replace(/^#+\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return ''
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`
}

export function compactJson(value, max = 88) {
  if (value == null || value === '') return ''
  try {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    if (!text || text === '{}' || text === '[]') return ''
    return text.length <= max ? text : `${text.slice(0, max - 1)}…`
  } catch {
    return oneLine(value, max)
  }
}

export function formatDuration(ms) {
  if (ms == null || Number.isNaN(Number(ms)) || ms < 0) return '—'
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)} 毫秒`
  const seconds = Math.round(value / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes < 60) return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
  const hours = Math.floor(minutes / 60)
  const minRest = minutes % 60
  return minRest ? `${hours} 小时 ${minRest} 分` : `${hours} 小时`
}

export function formatStamp(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function highlightJson(value) {
  if (value == null || value === '') return ''
  let json
  try {
    json = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  } catch {
    json = String(value)
  }
  const escaped = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped.replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(-?\d+(?:\.\d+)?)+\b|\b(true|false|null)\b/g,
    (match, string, colon, number, literal) => {
      if (string) {
        if (colon) return `<span class="json-key">${string}</span>${colon}`
        return `<span class="json-str">${string}</span>`
      }
      if (number) return `<span class="json-num">${number}</span>`
      if (literal) return `<span class="json-lit">${literal}</span>`
      return match
    },
  )
}

export function msBetween(start, end) {
  const a = Date.parse(start)
  const b = Date.parse(end)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.max(0, b - a)
}

function ledgerPreview(entries) {
  return (entries || [])
    .map((entry) => {
      const tag = LEDGER_KIND_LABEL[entry.kind] || entry.kind || ''
      const text = entry.text || entry.key || ''
      return [tag, text].filter(Boolean).join(' ')
    })
    .filter(Boolean)
    .join(' · ')
}

function clarifyPreview(payload) {
  const groups = payload.groups || []
  const questions = groups.map((group) => group.question).filter(Boolean)
  if (questions.length) return questions.join('；')
  return payload.question || ''
}

function withSearch(item) {
  item.searchText = [
    ROLE_LABEL[item.role] || item.role,
    item.headline,
    item.detail,
    item.resultPreview,
    item.title,
    item.name,
    item.content,
    item.reasoning,
    item.result,
    compactJson(item.arguments, 400),
    ledgerPreview(item.entries),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return item
}

function finishReasonLabel(reason) {
  return {
    stop: '正常结束',
    tool_calls: '转去调用工具',
    length: '达到长度上限',
    content_filter: '被安全策略打断',
  }[reason] || reason || ''
}

/**
 * Collapse a noisy event stream into a Codex-style linear log.
 * Deltas, step markers and job plumbing are folded away; tool.call/result
 * pair into one row; consecutive ledger snapshots group together.
 */
export function buildTimeline(events = [], { assistantName = '小吉' } = {}) {
  const assistant = assistantName || '小吉'
  const items = []
  const pendingTools = new Map()
  let turn = 0
  let step = 0
  let lastStepStartAt = ''
  const hasTurnStart = events.some((event) => event.type === 'agent.turn_start')

  const push = (item) => {
    items.push(withSearch(item))
    return item
  }

  for (const event of events) {
    const type = event.type
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {}
    if (payload.step) step = Number(payload.step) || step

    if (type === 'agent.step_start') {
      lastStepStartAt = event.created_at
      continue
    }
    if (SKIP_TYPES.has(type)) continue

    if (type === 'run.created') {
      if (!hasTurnStart && payload.question) {
        turn += 1
        push(makeUser(event, payload.question, turn, '用户提问'))
      }
      continue
    }

    if (type === 'agent.turn_start') {
      turn += 1
      push(makeUser(event, payload.question || '', turn, '用户提问'))
      continue
    }

    if (type === 'ask_user.answered') {
      push(makeUser(event, payload.answer || '', turn || 1, '澄清答复'))
      continue
    }

    if (type === 'assistant.message') {
      const calls = payload.tool_calls || []
      const content = payload.content || ''
      const reasoning = payload.reasoning || ''
      const isAnswer = !calls.length
      const headline = oneLine(content) || oneLine(reasoning) || (calls.length
        ? `准备调用 ${calls.length} 个工具`
        : '模型回应')
      push({
        id: `e-${event.cursor}`,
        role: 'assistant',
        kind: isAnswer ? 'answer' : 'message',
        turn,
        step: payload.step || step,
        title: isAnswer ? `${assistant}回答` : `${assistant}在想`,
        headline,
        detail: '',
        resultPreview: '',
        content,
        reasoning,
        arguments: null,
        result: content || reasoning,
        usage: payload.usage || null,
        finishReason: payload.finish_reason || '',
        finishReasonLabel: finishReasonLabel(payload.finish_reason),
        toolCalls: calls,
        hierarchy: `第 ${payload.step || step || 1} 步`,
        status: 'completed',
        startedAt: lastStepStartAt || event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: '',
        ok: true,
      })
      continue
    }

    if (type === 'tool.call') {
      const meta = toolMeta(payload.name)
      const args = displayToolArguments(payload.arguments ?? {})
      const item = withSearch({
        id: `tool-${payload.call_id || event.cursor}`,
        role: 'tool',
        kind: 'call',
        turn,
        step: payload.step || step,
        title: meta.label,
        name: payload.name || '',
        headline: meta.label,
        detail: compactJson(args),
        resultPreview: '',
        arguments: args,
        result: '',
        resultPayload: null,
        preview: null,
        hierarchy: `${assistant}消息`,
        status: 'running',
        ok: null,
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        callId: payload.call_id,
        content: '',
        reasoning: '',
      })
      pendingTools.set(payload.call_id, item)
      items.push(item)
      continue
    }

    if (type === 'tool.result') {
      const existing = pendingTools.get(payload.call_id)
      const output = payload.output || ''
      if (existing) {
        existing.ok = payload.ok !== false
        existing.status = existing.ok ? 'completed' : 'failed'
        existing.result = output
        existing.resultPreview = oneLine(output, 96)
        existing.resultPayload = payload
        existing.preview = payload.preview || null
        existing.endedAt = event.created_at
        existing.cursorEnd = event.cursor
        existing.type = 'tool.result'
        withSearch(existing)
      } else {
        const meta = toolMeta(payload.name)
        push({
          id: `tool-${payload.call_id || event.cursor}`,
          role: 'tool',
          kind: 'call',
          turn,
          step: payload.step || step,
          title: meta.label,
          name: payload.name || '',
          headline: meta.label,
          detail: '',
          resultPreview: oneLine(output, 96),
          arguments: null,
          result: output,
          resultPayload: payload,
          preview: payload.preview || null,
          hierarchy: `${assistant}消息`,
          status: payload.ok === false ? 'failed' : 'completed',
          ok: payload.ok !== false,
          startedAt: event.created_at,
          endedAt: event.created_at,
          cursor: event.cursor,
          cursorEnd: event.cursor,
          payload,
          type,
          callId: payload.call_id,
          content: '',
          reasoning: '',
        })
      }
      continue
    }

    if (type === 'agent.ledger.updated') {
      const last = items[items.length - 1]
      if (last?.role === 'tool' && last.name === 'update_ledger') continue
      const entries = Array.isArray(payload.entries) ? payload.entries : []
      if (last?.role === 'context' && last.kind === 'ledger') {
        last.entries = entries
        last.updates += 1
        last.endedAt = event.created_at
        last.cursorEnd = event.cursor
        last.payload = payload
        last.headline = last.updates > 1 ? `台账更新 · ${last.updates} 次` : '台账更新'
        last.detail = oneLine(ledgerPreview(entries), 120)
        withSearch(last)
        continue
      }
      push({
        id: `e-${event.cursor}`,
        role: 'context',
        kind: 'ledger',
        turn,
        step: step,
        title: '台账更新',
        headline: '台账更新',
        detail: oneLine(ledgerPreview(entries), 120),
        resultPreview: '',
        entries,
        updates: 1,
        hierarchy: '系统上下文',
        status: 'completed',
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: '',
        arguments: null,
        result: ledgerPreview(entries),
        content: '',
        reasoning: '',
        ok: true,
      })
      continue
    }

    if (type === 'ask_user.opened') {
      const preview = clarifyPreview(payload)
      push({
        id: `e-${event.cursor}`,
        role: 'context',
        kind: 'clarify',
        turn,
        step,
        title: '发起澄清',
        headline: '发起澄清',
        detail: oneLine(preview, 120),
        resultPreview: '',
        hierarchy: '系统上下文',
        status: 'completed',
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: 'ask_user',
        arguments: payload,
        result: preview,
        content: '',
        reasoning: '',
        ok: true,
      })
      continue
    }

    if (type === 'memory.auto_saved') {
      const text = payload.content || payload.text || '已把本轮确认写入个人记忆'
      push({
        id: `e-${event.cursor}`,
        role: 'context',
        kind: 'memory',
        turn,
        step,
        title: '已写入记忆',
        headline: '已写入记忆',
        detail: oneLine(text, 120),
        resultPreview: '',
        hierarchy: '系统上下文',
        status: 'completed',
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: '',
        arguments: payload,
        result: text,
        content: text,
        reasoning: '',
        ok: true,
      })
      continue
    }

    if (type === 'agent.done') {
      const lastAnswer = [...items].reverse().find((item) => item.kind === 'answer')
      const answer = payload.answer || ''
      if (lastAnswer && oneLine(lastAnswer.content, 80) === oneLine(answer, 80)) continue
      if (!answer) continue
      push({
        id: `e-${event.cursor}`,
        role: 'assistant',
        kind: 'answer',
        turn,
        step,
        title: `${assistant}回答`,
        headline: oneLine(answer),
        detail: '',
        resultPreview: '',
        content: answer,
        reasoning: '',
        arguments: null,
        result: answer,
        hierarchy: '最终回答',
        status: 'completed',
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: '',
        ok: true,
        toolCalls: [],
      })
      continue
    }

    if (type === 'agent.failed' || type === 'job.failed') {
      const message = payload.message || payload.code || '运行失败'
      push({
        id: `e-${event.cursor}`,
        role: 'system',
        kind: 'error',
        turn,
        step,
        title: type === 'job.failed' ? '后台任务失败' : '运行失败',
        headline: type === 'job.failed' ? '后台任务失败' : '运行失败',
        detail: oneLine(message, 120),
        resultPreview: '',
        hierarchy: '运行状态',
        status: 'failed',
        startedAt: event.created_at,
        endedAt: event.created_at,
        cursor: event.cursor,
        cursorEnd: event.cursor,
        payload,
        type,
        name: '',
        arguments: payload,
        result: message,
        content: message,
        reasoning: '',
        ok: false,
      })
      continue
    }
  }

  const calls = items.filter((item) => item.role === 'tool').length
  const turns = items.reduce((max, item) => Math.max(max, item.turn || 0), 0)
  return { items, calls, turns }
}

function makeUser(event, text, turn, title) {
  const content = rewriteLabLabelsInText(text)
  return {
    id: `e-${event.cursor}`,
    role: 'user',
    kind: title === '澄清答复' ? 'clarify-answer' : 'question',
    turn,
    step: 0,
    title,
    headline: oneLine(content, 220) || title,
    detail: '',
    resultPreview: '',
    content,
    reasoning: '',
    arguments: null,
    result: content,
    hierarchy: '用户提问',
    status: 'completed',
    startedAt: event.created_at,
    endedAt: event.created_at,
    cursor: event.cursor,
    cursorEnd: event.cursor,
    payload: event.payload || {},
    type: event.type,
    name: '',
    ok: true,
  }
}

function displayToolArguments(args) {
  if (!args || typeof args !== 'object') return args
  const next = { ...args }
  if (next.lab_id) next.lab_id = labDisplayName(next.lab_id) || next.lab_id
  if (next.lab_type) next.lab_type = labDisplayName(next.lab_type) || next.lab_type
  return next
}

export function insertTurnHeaders(items = []) {
  const rows = []
  let current = null
  for (const item of items) {
    if (item.turn && item.turn !== current) {
      current = item.turn
      rows.push({ rowKind: 'turn', id: `turn-${current}`, turn: current })
    }
    rows.push({ rowKind: 'item', ...item })
  }
  return rows
}

export function filterItems(items, query) {
  const needle = String(query || '').trim().toLowerCase()
  if (!needle) return items
  return items.filter((item) => (item.searchText || '').includes(needle))
}

export function buildConversation(items = []) {
  return items.filter((item) => {
    if (item.role === 'user') return true
    if (item.role === 'assistant' && item.kind === 'answer') return true
    return false
  })
}

function barColor(item, index) {
  if (item.role === 'user') return INPUT_COLOR
  if (item.role === 'tool') return item.ok === false ? TOOL_FAIL_COLOR : TOOL_COLOR
  if (item.role === 'context') return CONTEXT_COLOR
  return MODEL_COLORS[index % MODEL_COLORS.length]
}

function trackOf(item) {
  if (item.role === 'tool') return 'tools'
  if (item.role === 'assistant' || item.role === 'context') return 'model'
  if (item.role === 'user') return 'input'
  return null
}

export function buildGantt(items = []) {
  const tracks = { input: [], model: [], tools: [] }
  const placed = items.filter((item) => trackOf(item))
  if (!placed.length) return tracks
  const weights = placed.map((item) => {
    const elapsed = msBetween(item.startedAt, item.endedAt)
    return Math.max(elapsed || 0, 400)
  })
  const total = weights.reduce((sum, value) => sum + value, 0) || 1
  let acc = 0
  let modelIndex = 0
  placed.forEach((item, index) => {
    const track = trackOf(item)
    const left = (acc / total) * 100
    const width = Math.max((weights[index] / total) * 100, 1.1)
    acc += weights[index]
    const colorIndex = track === 'model' && item.role === 'assistant' ? modelIndex++ : modelIndex
    tracks[track].push({
      id: item.id,
      left,
      width: Math.min(width, Math.max(0, 100 - left)),
      color: barColor(item, colorIndex),
      title: item.title || item.headline,
    })
  })
  return tracks
}

export function computeDurationMs(events = [], run = null) {
  const times = events
    .map((event) => Date.parse(event.created_at))
    .filter((value) => !Number.isNaN(value))
  if (run?.created_at) {
    const start = Date.parse(run.created_at)
    const end = Date.parse(run.updated_at) || (times.length ? Math.max(...times) : start)
    if (!Number.isNaN(start) && !Number.isNaN(end)) return Math.max(0, end - start)
  }
  if (times.length < 2) return 0
  return Math.max(0, Math.max(...times) - Math.min(...times))
}

export function buildSessionModel(events = [], run = null, options = {}) {
  const timeline = buildTimeline(events, options)
  return {
    items: timeline.items,
    calls: timeline.calls,
    turns: timeline.turns || (run ? 1 : 0),
    conversation: buildConversation(timeline.items),
    gantt: buildGantt(timeline.items),
    durationMs: computeDurationMs(events, run),
  }
}

export const STATUS_TEXT = {
  completed: '已完成',
  failed: '失败',
  running: '进行中',
}
