import test from 'node:test'
import assert from 'node:assert/strict'
import { canEditBoard, canManageBoard, filterBoards, scopeCaption, boardPath } from '../src/workspace.js'

test('viewer, editor and owner controls reflect distinct capabilities', () => {
  assert.equal(canEditBoard({ my_role: 'viewer' }), false)
  assert.equal(canEditBoard({ my_role: 'editor' }), true)
  assert.equal(canManageBoard({ my_role: 'editor' }), false)
  assert.equal(canManageBoard({ my_role: 'owner' }), true)
  assert.equal(canEditBoard(null), false)
})
test('workspace separates received boards from personal boards while searching', () => {
  const boards = [{ name: 'DDI 商业经营', description: '年度', my_role: 'owner' },
    { name: '渠道行为', description: 'DDI 联动', my_role: 'viewer' }]
  assert.equal(filterBoards(boards, 'DDI', 'all').length, 2)
  assert.equal(filterBoards(boards, '', 'shared')[0].my_role, 'viewer')
  assert.equal(filterBoards(boards, '', 'mine')[0].my_role, 'owner')
  assert.equal(filterBoards(boards, '不存在', 'all').length, 0)
})
test('snapshot captions retain business scope and omit empty filters', () => {
  assert.equal(scopeCaption({ scope: { current_period: '2026-09', window: 'ytd', filters: { region: '华南', channel: '' } } }), '2026-09 · 年度累计 · 华南')
  assert.equal(scopeCaption({}), '保留收藏时的数据范围')
})
test('board routes encode IDs as one path component', () => {
  assert.equal(boardPath('a/b'), '/workspace/a%2Fb')
})
