import test from 'node:test'
import assert from 'node:assert/strict'
import { configuredLabs, createLabProfile, labConnectionPayload, labProfileChanged } from '../src/lib/labConnection.js'

test('loading a profile creates independent drafts with blank credential fields', () => {
  const saved = {
    endpoint_url: 'https://lab.example/query',
    token_configured: true,
    authorization: 'never-display-this',
    labs: [{ lab_id: 'actual', name: '实际销售', credential_configured: true, token: 'never-display-this-either' }],
  }
  const first = createLabProfile(saved)
  const second = createLabProfile(saved)
  assert.equal(first.authorization, '')
  assert.equal(first.labs[0].token, '')
  assert.equal(first.token_configured, true)
  assert.equal(first.labs[0].credential_configured, true)
  assert.equal(first.labs.length, 4)
  first.labs[0].api_access_id = 'draft-id'
  assert.equal(second.labs[0].api_access_id, '')
  assert.equal(saved.labs[0].api_access_id, undefined)
})

test('blank secrets are omitted so testing and switching preserve saved credentials', () => {
  const profile = createLabProfile({ endpoint_url: ' https://lab.example/query ', token_configured: true })
  profile.authorization = '  '
  profile.labs[0].token = '  '
  const bootcamp = labConnectionPayload('bootcamp', false, profile)
  const bailian = labConnectionPayload('bailian', true, profile)
  assert.equal('authorization' in bootcamp.profile, false)
  assert.equal(bootcamp.profile.endpoint_url, 'https://lab.example/query')
  assert.equal(bailian.mock_enabled, true)
  for (const lab of bailian.profile.labs) assert.equal('token' in lab, false)
  assert.equal('user_id' in bailian.profile, false)
})

test('only the selected provider credentials are included in the save request', () => {
  const profile = createLabProfile({ endpoint_url: 'https://lab.example/query' })
  profile.authorization = 'internal-service-token'
  profile.labs[0].token = 'bailian-token'
  profile.labs[0].api_access_id = ' lab-actual '
  profile.user_id = '12'
  profile.space_id = '24'
  const bootcamp = labConnectionPayload('bootcamp', false, profile)
  const bailian = labConnectionPayload('bailian', false, profile)
  assert.equal(bootcamp.profile.authorization, 'internal-service-token')
  assert.equal(bootcamp.profile.labs[0].api_access_id, 'lab-actual')
  assert.equal(bootcamp.profile.user_id, 12)
  assert.equal(bootcamp.profile.space_id, 24)
  assert.equal('token' in bootcamp.profile.labs[0], false)
  assert.equal(bailian.profile.labs[0].token, 'bailian-token')
  assert.equal('authorization' in bailian.profile, false)
  assert.equal('api_access_id' in bailian.profile.labs[0], false)
})

test('dirty state ignores server labels but detects credential replacement and per-platform changes', () => {
  const saved = { endpoint_url: 'https://lab.example/query', token_configured: true }
  const draft = createLabProfile(saved)
  assert.equal(labProfileChanged('bootcamp', draft, saved), false)
  draft.labs[0].name = 'Updated label'
  assert.equal(labProfileChanged('bootcamp', draft, saved), false)
  draft.authorization = 'new-secret'
  assert.equal(labProfileChanged('bootcamp', draft, saved), true)
  assert.equal(labProfileChanged('bailian', draft, saved), false)
  draft.labs[0].token = 'new-lab-secret'
  assert.equal(labProfileChanged('bailian', draft, saved), true)
})

test('live Bootcamp tests only configured mappings and accepts a single laboratory', () => {
  const profile = createLabProfile()
  profile.labs[1].api_access_id = 'demand-lab'
  profile.labs[2].api_access_id = '   '
  assert.deepEqual(configuredLabs('bootcamp', false, profile).map(lab => lab.lab_id), ['demand'])
  profile.labs[1].api_access_id = ''
  assert.equal(configuredLabs('bootcamp', false, profile).length, 0)
})

test('live Bailian uses saved credentials or newly entered tokens', () => {
  const profile = createLabProfile({ labs: [{ lab_id: 'actual', credential_configured: true }] })
  assert.deepEqual(configuredLabs('bailian', false, profile).map(lab => lab.lab_id), ['actual'])
  profile.labs[1].token = 'new-demand-token'
  profile.labs[2].token = '   '
  assert.deepEqual(configuredLabs('bailian', false, profile).map(lab => lab.lab_id), ['actual', 'demand'])
  assert.equal(configuredLabs('bailian', false, createLabProfile()).length, 0)
})

test('demo mode tests all four labs even without real credentials or mappings', () => {
  const profile = createLabProfile()
  for (const provider of ['bootcamp', 'bailian']) {
    assert.equal(configuredLabs(provider, false, profile).length, 0)
    assert.deepEqual(configuredLabs(provider, true, profile).map(lab => lab.lab_id), ['actual', 'demand', 'ext_simple', 'ext_complex'])
  }
})
