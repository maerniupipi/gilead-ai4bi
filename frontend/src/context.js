export const CONTEXT_LIMIT = 60000
export const CONTEXT_THRESHOLD = 48000

export function updateContext(message, event) {
  const { payload, id, type } = event
  const used = Number(payload.used_tokens)
  const limit = Number(payload.limit)
  if (!Number.isFinite(used) || used < 0 || !(limit > 0)) return
  const cursor = Number(id) || 0
  const reading = {
    used, limit, threshold: Number(payload.threshold_tokens) || CONTEXT_THRESHOLD,
    source: payload.source, phase: payload.phase, cursor,
  }
  if (!message.context || !cursor || cursor >= message.context.cursor) message.context = reading
  if (type !== 'context.compacted') return
  const before = Number(payload.before_tokens)
  if (!(before > used)) return
  const key = id || [payload.step, payload.phase, before, used].join('-')
  const notices = message.compactions || (message.compactions = [])
  if (!notices.some(item => item.key === key)) notices.push({ key, step: payload.step, before, used })
}

export function conversationContext(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i]
    if (msg.role !== 'a') continue
    if (msg.context) return msg.context
    const usage = msg.answer?.usage || msg.steps?.findLast(step => step.usage)?.usage
    if (usage?.prompt_tokens > 0) {
      return { used: usage.prompt_tokens + (usage.completion_tokens || 0), limit: CONTEXT_LIMIT,
        threshold: CONTEXT_THRESHOLD, source: 'provider' }
    }
  }
  return { used: messages.length ? null : 0, limit: CONTEXT_LIMIT, threshold: CONTEXT_THRESHOLD }
}

export const tokenNumber = value => Number(value).toLocaleString('en-US')
