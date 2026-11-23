import { streamSSE } from './sse.js'

const BASE = (import.meta.env?.VITE_API_BASE || '').replace(/\/$/, '')
let accessToken = ''
let unauthorizedHandler = null

export class ApiError extends Error {
  constructor(message, { status = 0, code = '', details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export function setAccessToken(token) {
  accessToken = token || ''
}

export function onUnauthorized(handler) {
  unauthorizedHandler = handler
}

function absoluteUrl(path) {
  if (/^https?:\/\//i.test(path)) return path
  return `${BASE}${path}`
}

async function errorFromResponse(response) {
  let payload = null
  try { payload = await response.json() } catch { /* non-JSON error */ }
  const detail = payload?.error || payload?.detail || payload
  const message = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(-1)?.[0] || '字段'}：${item.msg || '校验失败'}`).join('；')
      : detail?.message || response.statusText || `HTTP ${response.status}`
  return new ApiError(message, {
    status: response.status,
    code: detail?.code || payload?.code || '',
    details: detail,
  })
}

export async function request(method, path, body, { auth = true, headers = {}, signal, raw = false } = {}) {
  const requestToken = auth ? accessToken : ''
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const requestHeaders = { Accept: 'application/json', ...headers }
  if (body !== undefined && !isForm) requestHeaders['Content-Type'] = 'application/json'
  if (requestToken) requestHeaders.Authorization = `Bearer ${requestToken}`
  const response = await fetch(absoluteUrl(path), {
    method,
    headers: requestHeaders,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const error = await errorFromResponse(response)
    if (response.status === 401 && auth && requestToken === accessToken) unauthorizedHandler?.(error)
    throw error
  }
  if (raw) return response
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  if (type.includes('application/json')) return response.json()
  return response
}

function query(path, params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) search.set(key, value)
  })
  const suffix = search.toString()
  return suffix ? `${path}?${suffix}` : path
}

export const api = {
  prepareDocumentExport: (body, options = {}) => request('POST', '/api/v2/exports/prepare', body, options),
  downloadDocumentExport: async (body, options = {}) => {
    const response = await request('POST', '/api/v2/exports/download', body, { ...options, raw: true })
    const disposition = response.headers.get('content-disposition') || ''
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
    const filename = encoded ? decodeURIComponent(encoded) : `问数分析.${body.format}`
    return { blob: await response.blob(), filename }
  },
  login: (username, password) => request('POST', '/api/v2/auth/token', { username, password }, { auth: false }),
  me: () => request('GET', '/api/v2/auth/me'),
  users: () => request('GET', '/api/v2/auth/users'),
  createUser: (body) => request('POST', '/api/v2/auth/users', body),

  branding: () => request('GET', '/api/v2/branding', undefined, { auth: false }),
  updateBranding: (body) => request('PUT', '/api/v2/admin/branding', body),
  uploadBrandingLogo: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/v2/admin/branding/logo', form)
  },

  createChat: (question, sessionId, idempotencyKey, modelOptions = {}, { signal } = {}) => request('POST', '/api/v2/chat', {
    question,
    session_id: sessionId || null,
    ...modelOptions,
  }, { headers: { 'Idempotency-Key': idempotencyKey }, signal }),
  chatSessions: (params = {}) => request('GET', query('/api/v2/chat/sessions', params)),
  chatQuestions: (params = {}) => request('GET', query('/api/v2/chat/questions', params)),
  chatModels: () => request('GET', '/api/v2/chat/models'),
  chatMessages: (sessionId, { signal } = {}) => request('GET', `/api/v2/chat/sessions/${encodeURIComponent(sessionId)}/messages`, undefined, { signal }),
  waitingClarifications: (params = {}, { signal } = {}) => request('GET', query('/api/v2/clarifications/waiting', params), undefined, { signal }),
  clarify: (caseId, answers, modelOptions = {}, { signal } = {}) => request('POST', `/api/v2/clarifications/${encodeURIComponent(caseId)}/answers`, { answers, ...modelOptions }, { signal }),

  runs: (params = {}) => request('GET', query('/api/v2/runs', params)),
  runReport: (id, { signal } = {}) => request('GET', `/api/v2/runs/${encodeURIComponent(id)}/report`, undefined, { signal }),
  run: (id, { signal } = {}) => request('GET', `/api/v2/runs/${encodeURIComponent(id)}`, undefined, { signal }),
  cancelRun: (id) => request('POST', `/api/v2/runs/${encodeURIComponent(id)}/cancel`),
  runEvents: (id, params = {}, { signal } = {}) => request('GET', query(`/api/v2/runs/${encodeURIComponent(id)}/events`, params), undefined, { signal }),
  parseEvalWorkbook: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/v2/eval/workbooks/parse', form)
  },
  exportEvalWorkbook: async (payload) => {
    const response = await request('POST', '/api/v2/eval/workbooks/export', payload, { raw: true })
    return response.blob()
  },
  createEvalBatch: (filename) => request('POST', '/api/v2/eval/batches', { filename }),
  upsertEvalResult: (batchId, body) => request('PUT', `/api/v2/eval/batches/${encodeURIComponent(batchId)}/items`, body),
  listEvalResults: (batchId) => request('GET', `/api/v2/eval/batches/${encodeURIComponent(batchId)}/items`),
  getEvalResult: (batchId, sheet, row) => request('GET', query(`/api/v2/eval/batches/${encodeURIComponent(batchId)}/items/one`, { sheet, row })),
  exportEvalBatch: async (batchId) => {
    const response = await request('GET', `/api/v2/eval/batches/${encodeURIComponent(batchId)}/export`, undefined, { raw: true })
    return response.blob()
  },
  runTrace: (id) => request('GET', `/api/v2/runs/${encodeURIComponent(id)}/trace`),
  downloadRunExport: async (runId, exportId) => {
    const response = await request(
      'GET',
      `/api/v2/runs/${encodeURIComponent(runId)}/exports/${encodeURIComponent(exportId)}`,
      undefined,
      { raw: true },
    )
    const disposition = response.headers.get('content-disposition') || ''
    const starred = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    const quoted = disposition.match(/filename="([^"]+)"/i)
    let filename = '查询结果.xlsx'
    if (starred) {
      try { filename = decodeURIComponent(starred[1]) } catch { filename = starred[1] }
    } else if (quoted) {
      filename = quoted[1]
    }
    return { blob: await response.blob(), filename }
  },

  memory: () => request('GET', '/api/v2/memory'),
  addMemory: (entry) => request('POST', '/api/v2/memory', entry),
  updateMemory: (id, entry) => request('PUT', `/api/v2/memory/${encodeURIComponent(id)}`, entry),
  memoryHistory: (id) => request('GET', `/api/v2/memory/${encodeURIComponent(id)}/history`),
  revokeMemory: (id) => request('DELETE', `/api/v2/memory/${encodeURIComponent(id)}`),

  publishedKnowledge: (params = {}) => request('GET', query('/api/v2/knowledge/published', params)),
  knowledgeDocuments: () => request('GET', '/api/v2/knowledge/documents'),
  knowledgeDocument: id => request('GET', `/api/v2/knowledge/documents/${encodeURIComponent(id)}`),
  searchKnowledge: q => request('GET', query('/api/v2/knowledge/search', { q })),
  uploadKnowledge: file => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/v2/knowledge/documents', form)
  },
  knowledgeCandidates: (params = {}) => request('GET', query('/api/v2/knowledge/candidates', params)),
  createKnowledgeCandidate: (candidate) => request('POST', '/api/v2/knowledge/candidates', candidate),
  reviewQueue: (state = 'pending_review') => request('GET', query('/api/v2/admin/knowledge/reviews', { state })),
  approveKnowledge: (id, body) => request('POST', `/api/v2/admin/knowledge/reviews/${encodeURIComponent(id)}/approve`, body),
  rejectKnowledge: (id, body) => request('POST', `/api/v2/admin/knowledge/reviews/${encodeURIComponent(id)}/reject`, body),

  dataSources: () => request('GET', '/api/v2/admin/data-sources'),
  workspaceBoards: () => request('GET', '/api/v2/workspace/boards'),
  workspaceBoard: (id) => request('GET', `/api/v2/workspace/boards/${encodeURIComponent(id)}`),
  createWorkspaceBoard: (body) => request('POST', '/api/v2/workspace/boards', body),
  updateWorkspaceBoard: (id, body) => request('PUT', `/api/v2/workspace/boards/${encodeURIComponent(id)}`, body),
  deleteWorkspaceBoard: (id) => request('DELETE', `/api/v2/workspace/boards/${encodeURIComponent(id)}`),
  pinWorkspaceItem: (id, body) => request('POST', `/api/v2/workspace/boards/${encodeURIComponent(id)}/items`, body),
  saveWorkspaceLayout: (id, body) => request('PUT', `/api/v2/workspace/boards/${encodeURIComponent(id)}/layout`, body),
  workspaceAccess: (id) => request('GET', `/api/v2/workspace/boards/${encodeURIComponent(id)}/access`),
  saveWorkspaceAccess: (id, body) => request('PUT', `/api/v2/workspace/boards/${encodeURIComponent(id)}/access`, body),
  workspacePeople: (params = {}) => request('GET', query('/api/v2/workspace/people', params)),
  chatbotEntrances: () => request('GET', '/api/v2/chatbots/entrances', undefined, { auth: false }),
  chatbots: () => request('GET', '/api/v2/chatbots'),
  workbooks: (botId) => request('GET', `/api/v2/chatbots/${encodeURIComponent(botId)}/workbooks`),
  uploadWorkbook: (botId, file, uploadId) => {
    const form = new FormData()
    form.append('file', file)
    form.append('upload_id', uploadId)
    return request('POST', `/api/v2/chatbots/${encodeURIComponent(botId)}/workbook-uploads`, form)
  },
  pendingWorkbookUploads: (botId) => request('GET', `/api/v2/chatbots/${encodeURIComponent(botId)}/workbook-uploads`),
  workbookUpload: (botId, id) => request('GET', `/api/v2/chatbots/${encodeURIComponent(botId)}/workbook-uploads/${encodeURIComponent(id)}`),
  removeWorkbook: (botId, id) => request('DELETE', `/api/v2/chatbots/${encodeURIComponent(botId)}/workbooks/${encodeURIComponent(id)}`),
  adminChatbots: () => request('GET', '/api/v2/admin/chatbots'),
  createChatbot: (body) => request('POST', '/api/v2/admin/chatbots', body),
  updateChatbot: (id, body) => request('PUT', `/api/v2/admin/chatbots/${encodeURIComponent(id)}`, body),
  uploadChatbotWorkbook: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', '/api/v2/admin/chatbot-workbooks', form)
  },
  labDocuments: () => request('GET', '/api/v2/admin/lab-documents'),
  createDataSource: (body) => request('POST', '/api/v2/admin/data-sources', body),
  updateDataSource: (id, body) => request('PUT', `/api/v2/admin/data-sources/${encodeURIComponent(id)}`, body),
  testDataSource: (id) => request('POST', `/api/v2/admin/data-sources/${encodeURIComponent(id)}/test`),
  activateDataSource: (id) => request('POST', `/api/v2/admin/data-sources/${encodeURIComponent(id)}/activate`),
  disableDataSource: (id) => request('POST', `/api/v2/admin/data-sources/${encodeURIComponent(id)}/disable`),
  attachLab: (id, body) => request('POST', `/api/v2/admin/data-sources/${encodeURIComponent(id)}/labs`, body),
  detachLab: (id, labId) => request('DELETE', `/api/v2/admin/data-sources/${encodeURIComponent(id)}/labs/${encodeURIComponent(labId)}`),

  tools: () => request('GET', '/api/v2/admin/tools'),
  labPairs: () => request('GET', '/api/v2/admin/lab-connection/pairs'),
  saveLabPairs: body => request('PUT', '/api/v2/admin/lab-connection/pairs', body),
  myQuota: () => request('GET', '/api/v2/usage/me'),
  quotas: () => request('GET', '/api/v2/admin/usage/quotas'),
  resetQuota: id => request('POST', '/api/v2/admin/usage/quotas/' + encodeURIComponent(id) + '/reset'),
  labConnection: () => request('GET', '/api/v2/admin/lab-connection'),
  saveLabConnection: (body) => request('PUT', '/api/v2/admin/lab-connection', body),
  testLabConnection: (body) => request('POST', '/api/v2/admin/lab-connection/test', body),
  agents: () => request('GET', '/api/v2/admin/agents'),
  updateAgent: (id, body) => request('PATCH', `/api/v2/admin/agents/${encodeURIComponent(id)}`, body),
  enableAgent: (id) => request('POST', `/api/v2/admin/agents/${encodeURIComponent(id)}/enable`),
  disableAgent: (id) => request('POST', `/api/v2/admin/agents/${encodeURIComponent(id)}/disable`),
  queryToolConfig: () => request('GET', '/api/v2/admin/tools/query_db/config'),
  probeQueryTool: (body) => request('POST', '/api/v2/admin/tools/query_db/probe', body),
  saveQueryToolConfig: (body) => request('PUT', '/api/v2/admin/tools/query_db/config', body),

  modelConfigs: () => request('GET', '/api/v2/admin/model-configs'),
  createModelConfig: (body) => request('POST', '/api/v2/admin/model-configs', body),
  updateModelConfig: (id, body) => request('PATCH', `/api/v2/admin/model-configs/${encodeURIComponent(id)}`, body),
  deleteModelConfig: (id) => request('DELETE', `/api/v2/admin/model-configs/${encodeURIComponent(id)}`),
  activateModelConfig: (id) => request('POST', `/api/v2/admin/model-configs/${encodeURIComponent(id)}/activate`),
  testModelConfig: (id) => request('POST', `/api/v2/admin/model-configs/${encodeURIComponent(id)}/test`),

  skillPacks: () => request('GET', '/api/v2/admin/skill-packs'),
  createSkillPack: (body) => request('POST', '/api/v2/admin/skill-packs', body),
  draftAnswerSkill: (runId) => request('POST', `/api/v2/admin/skill-packs/from-run/${encodeURIComponent(runId)}/draft`),
  updateSkillPack: (id, body) => request('PATCH', `/api/v2/admin/skill-packs/${encodeURIComponent(id)}`, body),
  deleteSkillPack: (id) => request('DELETE', `/api/v2/admin/skill-packs/${encodeURIComponent(id)}`),
  mountableInsightSkillPacks: () => request('GET', '/api/v2/skill-packs/mountable'),

  auditEvents: (params = {}) => request('GET', query('/api/v2/admin/audit-events', params)),
  usageEvents: (params = {}) => request('GET', query('/api/v2/admin/usage/events', params)),
  usageSummary: (params = {}) => request('GET', query('/api/v2/admin/usage/summary', params)),
  usageTrend: (params = {}) => request('GET', query('/api/v2/admin/usage/trend', params)),

  submitFeedback: (body) => request('POST', '/api/v2/feedback', body),
  getFeedback: (runId) => request('GET', `/api/v2/feedback/${encodeURIComponent(runId)}`),
  adminFeedback: (params = {}) => request('GET', query('/api/v2/admin/feedback', params)),

}

export function streamRunEvents(eventsUrl, {
  signal,
  lastEventId = '',
  onEvent,
  onHeartbeat,
  maxReconnects = 5,
} = {}) {
  const streamToken = accessToken
  return streamSSE({
    url: absoluteUrl(eventsUrl),
    token: streamToken,
    signal,
    lastEventId,
    maxReconnects,
    onHeartbeat,
    onEvent: (event) => {
      const envelope = event.json || {}
      return onEvent?.({
        id: event.id || envelope.cursor || '',
        type: event.event || envelope.type || 'message',
        payload: envelope.payload ?? envelope,
        envelope,
      })
    },
  }).catch((error) => {
    if (error?.status === 401 && streamToken === accessToken) unauthorizedHandler?.(error)
    throw error
  })
}
