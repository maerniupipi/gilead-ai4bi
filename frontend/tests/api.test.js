import test from 'node:test'
import assert from 'node:assert/strict'
import { api, onUnauthorized, request, setAccessToken } from '../src/api/backend.js'

function unauthorizedResponse() {
  return new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'expired' } }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('a stale request cannot clear a newer authenticated session', async () => {
  const previousFetch = globalThis.fetch
  let release
  globalThis.fetch = () => new Promise(resolve => { release = resolve })
  let unauthorizedCalls = 0
  onUnauthorized(() => { unauthorizedCalls += 1 })
  try {
    setAccessToken('old-token')
    const pending = request('GET', '/api/v2/auth/me')
    setAccessToken('new-token')
    release(unauthorizedResponse())
    await assert.rejects(pending, error => error.status === 401)
    assert.equal(unauthorizedCalls, 0)

    globalThis.fetch = async () => unauthorizedResponse()
    await assert.rejects(request('GET', '/api/v2/auth/me'), error => error.status === 401)
    assert.equal(unauthorizedCalls, 1)
  } finally {
    setAccessToken('')
    onUnauthorized(null)
    globalThis.fetch = previousFetch
  }
})

test('personal memory update and history use owner-scoped encoded endpoints', async () => {
  const previousFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options })
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    setAccessToken('memory-token')
    await api.updateMemory('memory/a', { category: 'scope', content: '渠道=EC' })
    await api.memoryHistory('memory/a')
    assert.equal(requests[0].url, '/api/v2/memory/memory%2Fa')
    assert.equal(requests[0].options.method, 'PUT')
    assert.equal(requests[0].options.headers.Authorization, 'Bearer memory-token')
    assert.equal(requests[1].url, '/api/v2/memory/memory%2Fa/history')
    assert.equal(requests[1].options.method, 'GET')
  } finally {
    setAccessToken('')
    globalThis.fetch = previousFetch
  }
})

test('eval workbook parse sends multipart without forcing JSON content type', async () => {
  const previousFetch = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url: String(url), options }
    return new Response(JSON.stringify({ filename: 'a.xlsx', sheets: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    setAccessToken('eval-token')
    const file = new File(['abc'], 'a.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    await api.parseEvalWorkbook(file)
    assert.equal(captured.url, '/api/v2/eval/workbooks/parse')
    assert.equal(captured.options.method, 'POST')
    assert.ok(captured.options.body instanceof FormData)
    assert.equal(captured.options.headers['Content-Type'], undefined)
    assert.equal(captured.options.headers.Authorization, 'Bearer eval-token')
  } finally {
    setAccessToken('')
    globalThis.fetch = previousFetch
  }
})

test('branding read is public and write uses admin endpoints', async () => {
  const previousFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options })
    return new Response(JSON.stringify({ character_name: '小英', themes: [], logos: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    setAccessToken('admin-token')
    await api.branding()
    await api.updateBranding({ character_name: '小柯', company_intro: '示例助手', theme_id: 'harbor', logo_preset_id: 'corgi' })
    const file = new File(['abc'], 'mark.png', { type: 'image/png' })
    await api.uploadBrandingLogo(file)
    await api.users()
    await api.createUser({ username: 'bob', password: 'password1', role: 'user' })
    assert.equal(requests[0].url, '/api/v2/branding')
    assert.equal(requests[0].options.headers.Authorization, undefined)
    assert.equal(requests[1].url, '/api/v2/admin/branding')
    assert.equal(requests[1].options.method, 'PUT')
    assert.equal(requests[1].options.headers.Authorization, 'Bearer admin-token')
    assert.equal(requests[2].url, '/api/v2/admin/branding/logo')
    assert.ok(requests[2].options.body instanceof FormData)
    assert.equal(requests[2].options.headers['Content-Type'], undefined)
    assert.equal(requests[3].url, '/api/v2/auth/users')
    assert.equal(requests[4].url, '/api/v2/auth/users')
    assert.equal(requests[4].options.method, 'POST')
  } finally {
    setAccessToken('')
    globalThis.fetch = previousFetch
  }
})

test('chat questions list uses limit and offset query params', async () => {
  const previousFetch = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => {
    captured = { url: String(url), options }
    return new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 20 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    setAccessToken('chat-token')
    await api.chatQuestions({ limit: 20, offset: 20 })
    assert.equal(captured.url, '/api/v2/chat/questions?limit=20&offset=20')
    assert.equal(captured.options.method, 'GET')
    assert.equal(captured.options.headers.Authorization, 'Bearer chat-token')
  } finally {
    setAccessToken('')
    globalThis.fetch = previousFetch
  }
})
