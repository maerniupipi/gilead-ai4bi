const DEFAULT_RETRY_MS = 900

function abortError() {
  return new DOMException('请求已取消', 'AbortError')
}

export function abortableDelay(ms, signal) {
  if (signal?.aborted) return Promise.reject(abortError())
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(abortError())
    }, { once: true })
  })
}

async function* responseChunks(body) {
  const reader = body.getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      yield value
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Parse an SSE byte/string stream according to the EventSource line grammar.
 * Handles CRLF split across chunks, multiline data, comments/heartbeats and EOF.
 */
export async function parseSSE(source, { onEvent, onComment } = {}) {
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = ''
  let eventId = ''
  let retry
  let dataLines = []

  const dispatch = async () => {
    if (!dataLines.length) {
      eventName = ''
      retry = undefined
      return
    }
    const event = {
      event: eventName || 'message',
      id: eventId,
      data: dataLines.join('\n'),
      retry,
    }
    eventName = ''
    retry = undefined
    dataLines = []
    await onEvent?.(event)
  }

  const acceptLine = async (rawLine) => {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (!line) return dispatch()
    if (line.startsWith(':')) {
      await onComment?.(line.slice(1).replace(/^ /, ''))
      return
    }
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') eventName = value
    else if (field === 'data') dataLines.push(value)
    else if (field === 'id' && !value.includes('\0')) eventId = value
    else if (field === 'retry' && /^\d+$/.test(value)) retry = Number(value)
  }

  for await (const chunk of source) {
    buffer += typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true })
    let newline
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline)
      buffer = buffer.slice(newline + 1)
      await acceptLine(line)
    }
  }
  buffer += decoder.decode()
  if (buffer) await acceptLine(buffer)
  await dispatch()
}

function parseData(text) {
  if (!text) return null
  try { return JSON.parse(text) } catch {
    const error = new Error('服务端返回了无法解析的 SSE 数据')
    error.code = 'INVALID_SSE_DATA'
    throw error
  }
}

/**
 * Fetch a run event stream. Network failures reconnect with Last-Event-ID and
 * the matching `after` cursor; a clean server close is treated as completion.
 */
export async function streamSSE({
  url,
  token,
  signal,
  lastEventId = '',
  maxReconnects = 5,
  onEvent,
  onHeartbeat,
  fetchImpl = fetch,
}) {
  let cursor = lastEventId ? String(lastEventId) : ''
  let retries = 0
  let retryMs = DEFAULT_RETRY_MS

  for (;;) {
    if (signal?.aborted) throw abortError()
    try {
      const target = new URL(url, window.location.origin)
      if (cursor) target.searchParams.set('after', cursor)
      if (!target.searchParams.has('follow')) target.searchParams.set('follow', 'true')
      const headers = { Accept: 'text/event-stream' }
      if (token) headers.Authorization = `Bearer ${token}`
      if (cursor) headers['Last-Event-ID'] = cursor
      const response = await fetchImpl(target.toString(), { headers, signal })
      if (!response.ok || !response.body) {
        const error = new Error(`事件流连接失败（HTTP ${response.status}）`)
        error.status = response.status
        throw error
      }
      await parseSSE(responseChunks(response.body), {
        onComment: onHeartbeat,
        onEvent: async (event) => {
          if (event.retry != null) retryMs = Math.max(250, event.retry)
          const nextId = event.id || ''
          if (nextId && cursor && Number(nextId) <= Number(cursor)) return
          const json = parseData(event.data)
          await onEvent?.({ ...event, json })
          retries = 0
          if (nextId) cursor = nextId
        },
      })
      return cursor
    } catch (error) {
      if (signal?.aborted || error?.name === 'AbortError') throw abortError()
      if (error?.status && error.status < 500) throw error
      if (retries >= maxReconnects) throw error
      const wait = Math.min(retryMs * (2 ** retries), 8000)
      retries += 1
      await abortableDelay(wait, signal)
    }
  }
}
