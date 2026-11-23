import test from 'node:test'
import assert from 'node:assert/strict'
import { TEMPLATE, compose, parse, reconcile, sortEntries } from '../src/utils/memoryDoc.js'

const entry = (id, category, content, created_at) => ({ id, category, content, created_at })

test('groups entries under one heading per category, in the declared order', () => {
  const entries = sortEntries([
    entry('c', 'terminology', '大盘指全国合计', '2026-08-01'),
    entry('a', 'preference', '先给结论', '2026-08-02'),
    entry('b', 'preference', '再列口径', '2026-08-03'),
  ])
  assert.equal(
    compose(entries),
    '## 偏好\n- 先给结论\n- 再列口径\n\n## 术语\n- 大盘指全国合计\n',
  )
})

test('a document survives a round trip through compose and parse', () => {
  const entries = sortEntries([
    entry('a', 'preference', '先给结论', '2026-08-01'),
    entry('b', 'metric_definition', '销售额不含税\n口径与财报一致', '2026-08-02'),
    entry('c', 'terminology', '大盘指全国合计', '2026-08-03'),
  ])
  assert.deepEqual(
    parse(compose(entries)),
    entries.map(({ category, content }) => ({ category, content })),
  )
})

test('the default template parses into one item per bullet', () => {
  const items = parse(TEMPLATE)
  assert.equal(items.length, 5)
  assert.deepEqual(
    items.map((item) => item.category),
    ['preference', 'metric_definition', 'scope', 'terminology', 'recent'],
  )
})

test('a heading the labels do not know becomes its own category', () => {
  assert.deepEqual(parse('## 汇报口径\n- 只看含税口径'), [
    { category: '汇报口径', content: '只看含税口径' },
  ])
})

test('text before any heading falls into the write API default category', () => {
  assert.deepEqual(parse('先给结论'), [{ category: 'preference', content: '先给结论' }])
})

test('an edited bullet updates its row rather than replacing it', () => {
  const existing = [entry('m1', 'preference', '先给结论', '2026-08-01')]
  const plan = reconcile(parse('## 偏好\n- 先给结论，再给口径'), existing)
  assert.deepEqual(plan.create, [])
  assert.deepEqual(plan.revoke, [])
  assert.equal(plan.update.length, 1)
  assert.equal(plan.update[0].entry.id, 'm1')
  assert.equal(plan.update[0].content, '先给结论，再给口径')
})

test('reordering a section rewrites nothing, because untouched text claims its own row', () => {
  const existing = [
    entry('m1', 'preference', '先给结论', '2026-08-01'),
    entry('m2', 'preference', '再列口径', '2026-08-02'),
  ]
  const plan = reconcile(parse('## 偏好\n- 再列口径\n- 先给结论'), existing)
  assert.deepEqual(plan, { create: [], update: [], revoke: [] })
})

test('replacing one bullet reuses its row, so the old text stays in that row history', () => {
  const existing = [
    entry('m1', 'preference', '先给结论', '2026-08-01'),
    entry('m2', 'preference', '再列口径', '2026-08-02'),
  ]
  const plan = reconcile(parse('## 偏好\n- 先给结论\n- 最后给SQL'), existing)
  assert.deepEqual(plan.create, [])
  assert.deepEqual(plan.revoke, [])
  assert.equal(plan.update.length, 1)
  assert.equal(plan.update[0].entry.id, 'm2')
  assert.equal(plan.update[0].content, '最后给SQL')
})

test('a bullet added past the end of a section creates a new row', () => {
  const existing = [entry('m1', 'preference', '先给结论', '2026-08-01')]
  const plan = reconcile(parse('## 偏好\n- 先给结论\n- 最后给SQL'), existing)
  assert.deepEqual(plan.update, [])
  assert.deepEqual(plan.revoke, [])
  assert.deepEqual(plan.create, [{ category: 'preference', content: '最后给SQL' }])
})

test('dropping a whole section revokes every row it held', () => {
  const existing = [
    entry('m1', 'preference', '先给结论', '2026-08-01'),
    entry('m2', 'terminology', '大盘指全国合计', '2026-08-02'),
  ]
  const plan = reconcile(parse('## 偏好\n- 先给结论'), existing)
  assert.deepEqual(plan.create, [])
  assert.deepEqual(plan.update, [])
  assert.deepEqual(
    plan.revoke.map((item) => item.id),
    ['m2'],
  )
})

test('an unchanged document plans no writes at all', () => {
  const entries = sortEntries([
    entry('m1', 'preference', '先给结论', '2026-08-01'),
    entry('m2', 'scope', '默认按当年 YTD', '2026-08-02'),
  ])
  const plan = reconcile(parse(compose(entries)), entries)
  assert.deepEqual(plan, { create: [], update: [], revoke: [] })
})
