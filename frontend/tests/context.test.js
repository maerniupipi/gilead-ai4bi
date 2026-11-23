import test from 'node:test'
import assert from 'node:assert/strict'
import { conversationContext, updateContext } from '../src/context.js'

const compressed = { type: 'context.compacted', id: '32',
  payload: { step: 3, phase: 'input', before_tokens: 48612, used_tokens: 21409,
    threshold_tokens: 48000, limit: 60000, source: 'tokenizer' } }

test('live and replayed compression update the same meter and create one notice', () => {
  const msg = { role: 'a' }
  updateContext(msg, compressed)
  updateContext(msg, compressed)
  updateContext(msg, { ...compressed, type: 'context.updated', id: '31',
    payload: { ...compressed.payload, used_tokens: 47000 } })
  assert.equal(msg.compactions.length, 1)
  assert.equal(conversationContext([msg, { role: 'u' }]).used, 21409)
  updateContext(msg, { ...compressed, type: 'context.updated', id: '33',
    payload: { ...compressed.payload, used_tokens: 21779, source: 'provider' } })
  assert.equal(conversationContext([msg]).used, 21779)
  assert.equal(conversationContext([]).used, 0)
})

test('legacy usage and sessions without readings have different display states', () => {
  const old = { role: 'a', steps: [{ usage: { prompt_tokens: 200, completion_tokens: 30 } }] }
  assert.equal(conversationContext([old]).used, 230)
  assert.equal(conversationContext([{ role: 'u' }]).used, null)
})
