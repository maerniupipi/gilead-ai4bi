import test from 'node:test'
import assert from 'node:assert/strict'
import { api } from '../src/api/backend.js'
import { chooseChatbot, currentChatbot, loadChatbots, loadSessions, restoreSession, store } from '../src/store.js'

test('guest selection opens login with the chosen Chatbot', async () => {
  store.token = ''
  store.chatbotChooserOpen = true
  assert.equal(await chooseChatbot('ddi'), false)
  assert.equal(store.pendingChatbotId, 'ddi')
  assert.equal(store.loginOpen, true)
  assert.equal(store.chatbotChooserOpen, true)
})

test('dual entrances allow switching back from personal XLSX to database chat', async () => {
  const previous = api.chatSessions
  api.chatSessions = async ({ chatbot_id }) => [{ id: `${chatbot_id}-history` }]
  try {
    store.token = 'unit-test'
    store.chatbots = [
      { id: 'ddi', name: '数据库问数助手', workbooks: [] },
      { id: 'xlsx', name: 'XLSX 问数助手', personal_uploads: true, workbooks: [{ id: 'private' }] },
    ]
    store.chatbotId = 'ddi'
    await chooseChatbot('xlsx')
    assert.equal(currentChatbot().personal_uploads, true)
    assert.deepEqual(store.sessions, [{ id: 'xlsx-history' }])
    await chooseChatbot('ddi')
    assert.equal(currentChatbot().id, 'ddi')
    assert.deepEqual(currentChatbot().workbooks, [])
    assert.deepEqual(store.sessions, [{ id: 'ddi-history' }])
  } finally { api.chatSessions = previous }
})

test('an expired saved login still loads both public entrances', async () => {
  const previous = api.chatbotEntrances
  api.chatbotEntrances = async () => [{ id: 'ddi' }, { id: 'xlsx', personal_uploads: true }]
  try {
    store.token = 'expired-token'
    store.expiresAt = '2020-01-01T00:00:00Z'
    store.chatbots = []
    assert.equal(await restoreSession(), false)
    assert.equal(store.token, '')
    assert.equal(store.authReady, true)
    assert.deepEqual(store.chatbots.map(bot => bot.id), ['ddi', 'xlsx'])
    assert.equal(store.chatbotChooserOpen, true)
  } finally { api.chatbotEntrances = previous }
})

test('an invalid saved login recovers the public assistant catalog', async () => {
  const previousMe = api.me, previousCatalog = api.chatbotEntrances
  api.me = async () => { throw Object.assign(new Error('expired'), { status: 401 }) }
  api.chatbotEntrances = async () => [{ id: 'ddi' }, { id: 'xlsx', personal_uploads: true }]
  try {
    store.token = 'invalid-token'
    store.expiresAt = ''
    store.chatbots = []
    assert.equal(await restoreSession(), false)
    assert.equal(store.token, '')
    assert.deepEqual(store.chatbots.map(bot => bot.id), ['ddi', 'xlsx'])
  } finally { api.me = previousMe; api.chatbotEntrances = previousCatalog }
})

test('switching Chatbot clears conversation and prior skill, and requests scoped history', async () => {
  const previous = api.chatSessions
  const requests = []
  api.chatSessions = async params => { requests.push(params); return [{ id: 'behavior-session' }] }
  try {
    store.token = 'unit-test'
    store.chatbots = [{ id: 'ddi' }, { id: 'behavior' }]
    store.chatbotId = 'ddi'
    store.sessionId = 'old-ddi'
    store.messages = [{ role: 'u', text: 'DDI question' }]
    store.insightMode = true
    Object.assign(store.insightSkill, { skillPackId: 'ddi_analysis', customPrompt: 'old', skillName: 'DDI' })
    await chooseChatbot('behavior')
    assert.equal(currentChatbot().id, 'behavior')
    assert.equal(store.sessionId, '')
    assert.deepEqual(store.messages, [])
    assert.equal(store.insightMode, false)
    assert.equal(store.insightSkill.skillPackId, '')
    assert.equal(store.chatbotChooserOpen, false)
    assert.deepEqual(requests, [{ chatbot_id: 'behavior' }])
    assert.deepEqual(store.sessions.map(s => s.id), ['behavior-session'])
    await assert.rejects(chooseChatbot('unauthorized'), /使用权/)
  } finally { api.chatSessions = previous }
})

test('late history response cannot overwrite another Chatbot', async () => {
  const previous = api.chatSessions
  let resolve
  api.chatSessions = () => new Promise(done => { resolve = done })
  try {
    store.token = 'unit-test'
    store.chatbotId = 'ddi'
    const request = loadSessions()
    store.chatbotId = 'behavior'
    store.sessions = [{ id: 'behavior-session' }]
    resolve([{ id: 'old-ddi' }])
    await request
    assert.deepEqual(store.sessions.map(s => s.id), ['behavior-session'])
  } finally { api.chatSessions = previous }
})

test('revoking access returns to chooser and removes old conversation state', async () => {
  const previous = api.chatbots
  api.chatbots = async () => [{ id: 'ddi' }]
  try {
    store.token = 'unit-test'
    store.chatbotId = 'behavior'
    store.sessions = [{ id: 'private-session' }]
    store.messages = [{ role: 'u', text: 'private' }]
    await loadChatbots()
    assert.equal(store.chatbotId, '')
    assert.equal(store.chatbotChooserOpen, true)
    assert.deepEqual(store.sessions, [])
    assert.deepEqual(store.messages, [])
  } finally { api.chatbots = previous }
})

test('the single personal XLSX assistant opens directly after authentication', async () => {
  const previous = api.chatbots
  api.chatbots = async () => [{ id: 'xlsx', personal_uploads: true, workbooks: [] }]
  try {
    store.token = 'unit-test'
    store.chatbotId = 'ddi'
    store.messages = [{ role: 'u', text: 'old conversation' }]
    store.chatbotChooserOpen = true
    await loadChatbots()
    assert.equal(store.chatbotId, 'xlsx')
    assert.equal(store.chatbotChooserOpen, false)
    assert.deepEqual(store.messages, [])
  } finally { api.chatbots = previous }
})

test('guests go to XLSX login without choosing an assistant', async () => {
  const previous = api.chatbotEntrances
  api.chatbotEntrances = async () => [{ id: 'xlsx', personal_uploads: true }]
  try {
    store.token = ''
    store.chatbotId = ''
    store.pendingChatbotId = ''
    await loadChatbots()
    assert.equal(store.chatbotId, 'xlsx')
    assert.equal(store.pendingChatbotId, 'xlsx')
    assert.equal(store.chatbotChooserOpen, false)
  } finally { api.chatbotEntrances = previous }
})
