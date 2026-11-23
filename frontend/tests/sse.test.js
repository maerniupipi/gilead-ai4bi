import test from 'node:test'
import assert from 'node:assert/strict'
import { parseSSE, streamSSE } from '../src/api/sse.js'

async function parse(chunks) {
  const events = []
  const comments = []
  await parseSSE((async function* () {
    for (const chunk of chunks) yield chunk
  })(), {
    onEvent: event => events.push(event),
    onComment: comment => comments.push(comment),
  })
  return { events, comments }
}

test('parses CRLF, multiline data and a heartbeat across chunk boundaries', async () => {
  const result = await parse([
    'id: 4\r\nevent: answer.completed\r\nda',
    'ta: {"text":"line 1"}\r\ndata: line 2\r\n\r',
    '\n: heartbeat 4\r\n\r\n',
  ])
  assert.deepEqual(result.events, [{
    id: '4',
    event: 'answer.completed',
    data: '{"text":"line 1"}\nline 2',
    retry: undefined,
  }])
  assert.deepEqual(result.comments, ['heartbeat 4'])
})

test('dispatches a final event without a trailing blank line', async () => {
  const result = await parse(['id: 9\nevent: fact.created\ndata: {"fact_id":"f-9"}'])
  assert.equal(result.events.length, 1)
  assert.equal(result.events[0].id, '9')
  assert.equal(result.events[0].event, 'fact.created')
})

test('keeps the last event id and ignores comment-only blocks', async () => {
  const result = await parse(['id: 2\ndata: first\n\n: ping\n\ndata: second\n\n'])
  assert.deepEqual(result.events.map(event => [event.id, event.data]), [
    ['2', 'first'],
    ['2', 'second'],
  ])
  assert.deepEqual(result.comments, ['ping'])
})

test('reads retry and ignores invalid event ids containing NUL', async () => {
  const result = await parse(['id: safe\ndata: one\n\nid: bad\0id\nretry: 1500\ndata: two\n\n'])
  assert.equal(result.events[1].id, 'safe')
  assert.equal(result.events[1].retry, 1500)
})

test('reconnects with after and Last-Event-ID after an interrupted body', async () => {
  const encoder = new TextEncoder()
  const requests = []
  const received = []
  let call = 0
  const fetchImpl = async (url, options) => {
    requests.push({ url, headers: options.headers })
    call += 1
    if (call === 1) {
      let pulled = false
      return {
        ok: true,
        status: 200,
        body: new ReadableStream({
          pull(controller) {
            if (!pulled) {
              pulled = true
              controller.enqueue(encoder.encode('id: 1\nevent: first\nretry: 1\ndata: {"cursor":1}\n\n'))
            } else controller.error(new Error('connection reset'))
          },
        }),
      }
    }
    return {
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('id: 2\nevent: second\ndata: {"cursor":2}\n\n'))
          controller.close()
        },
      }),
    }
  }
  const previousWindow = globalThis.window
  globalThis.window = { location: { origin: 'http://quick.test' } }
  try {
    const lastId = await streamSSE({
      url: '/events',
      token: 'test-token',
      fetchImpl,
      maxReconnects: 2,
      onEvent: event => received.push([event.id, event.event]),
    })
    assert.equal(lastId, '2')
    assert.deepEqual(received, [['1', 'first'], ['2', 'second']])
    assert.equal(new URL(requests[1].url).searchParams.get('after'), '1')
    assert.equal(requests[1].headers['Last-Event-ID'], '1')
    assert.equal(requests[1].headers.Authorization, 'Bearer test-token')
  } finally {
    globalThis.window = previousWindow
  }
})

test('does not commit a cursor until the event handler succeeds', async () => {
  const encoder = new TextEncoder()
  const requests = []
  let handlerCalls = 0
  const fetchImpl = async (url, options) => {
    requests.push({ url, headers: options.headers })
    return {
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('id: 7\nevent: fact.created\nretry: 1\ndata: {"cursor":7}\n\n'))
          controller.close()
        },
      }),
    }
  }
  const previousWindow = globalThis.window
  globalThis.window = { location: { origin: 'http://quick.test' } }
  try {
    const lastId = await streamSSE({
      url: '/events',
      fetchImpl,
      maxReconnects: 1,
      onEvent: () => {
        handlerCalls += 1
        if (handlerCalls === 1) throw new Error('render failed')
      },
    })
    assert.equal(lastId, '7')
    assert.equal(handlerCalls, 2)
    assert.equal(requests.length, 2)
    assert.equal(new URL(requests[1].url).searchParams.has('after'), false)
    assert.equal(requests[1].headers['Last-Event-ID'], undefined)
  } finally {
    globalThis.window = previousWindow
  }
})

test('stops reconnecting after consecutive deterministic handler failures', async () => {
  const encoder = new TextEncoder()
  let requests = 0
  const previousWindow = globalThis.window
  globalThis.window = { location: { origin: 'http://quick.test' } }
  try {
    await assert.rejects(() => streamSSE({
      url: '/events',
      maxReconnects: 1,
      fetchImpl: async () => {
        requests += 1
        return {
          ok: true,
          status: 200,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode('id: 8\nevent: broken\nretry: 1\ndata: {"cursor":8}\n\n'))
              controller.close()
            },
          }),
        }
      },
      onEvent: () => { throw new Error('deterministic render failure') },
    }), /deterministic render failure/)
    assert.equal(requests, 2)
  } finally {
    globalThis.window = previousWindow
  }
})
