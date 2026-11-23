import test from 'node:test'
import assert from 'node:assert/strict'
import { ASK_HOME_EXAMPLES, homeExamplesForChatbot } from '../src/data/homeExamples.js'

test('DDI retains the verified six starter questions', () => {
  assert.deepEqual(homeExamplesForChatbot({ category: 'ddi' }, false), ASK_HOME_EXAMPLES)
})

test('behavior workbooks have questions in their own metric vocabulary', () => {
  const bot = { category: 'behavior', workbook_ids: ['sample'] }
  for (const insight of [false, true]) {
    const questions = homeExamplesForChatbot(bot, insight).flatMap(item => item.questions)
    assert.equal(questions.length, 6)
    assert.ok(questions.every(question => !/销售|DDI|金额/.test(question)))
    assert.ok(questions.some(question => /转化/.test(question)))
  }
})

test('new workbook bots do not assume DDI or behavior fields', () => {
  const questions = homeExamplesForChatbot({ category: 'general', workbook_ids: ['custom'] }, false)
    .flatMap(item => item.questions)
  assert.ok(questions.every(question => !/DDI|销售金额|活跃用户|转化率/.test(question)))
})
