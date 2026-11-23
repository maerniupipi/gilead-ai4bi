import test from 'node:test'
import assert from 'node:assert/strict'
import { reportView } from '../src/reports/model.js'
import { createSampleReport } from '../scripts/sample-data.mjs'
import { buildReportHtml, prepareReport } from '../src/reports/template.js'

const small = () => ({
  columns: [{ key: 'date' }, { key: 'region' }, { key: 'sales' }, { key: 'target' }],
  date_field: 'date', dimension: 'region', period: 'month', current_period: '2026-09',
  metrics: { amount: 'sales', target: 'target', prior: 'prior' },
  rows: [{ date: '2026-09-01', region: '华东', sales: 80, target: 40, prior: 60 },
    { date: '2026-09-02', region: '华南', sales: 120, target: 160, prior: 100 }],
})

test('workbook reports preserve business field labels and distinguish people from currency', () => {
  const input = small()
  input.source = { domain: 'workbook' }
  input.metrics = { amount: 'active' }
  input.columns = [{ key: 'date' }, { key: 'region' }, { key: 'active', label: '活跃用户', format: 'number' }]
  input.rows = [{ date: '2026-09-01', region: '华东', active: 120 }]
  const { report } = prepareReport(input)
  assert.equal(report.columns.find(c => c.key === 'active').label, '活跃用户')
  assert.equal(reportView(report).unit, '人')
  input.metrics = { amount: 'revenue' }
  input.columns = [{ key: 'date' }, { key: 'region' }, { key: 'revenue', label: '销售金额', format: 'money' }]
  assert.equal(prepareReport(input).report.metric_units.amount, 'CNY')
})

test('all report surfaces use ratio of sums and the same filtered dataset', () => {
  const report = small()
  const all = reportView(report)
  assert.equal(all.totals.attainment, 100)
  assert.equal(all.trend[0].attainment, 100)
  assert.equal(all.groups.reduce((sum, row) => sum + row.actual, 0), all.totals.actual)
  const east = reportView(report, { filters: { region: '华东' } })
  assert.equal(east.totals.actual, 80)
  assert.equal(east.totals.attainment, 200)
  assert.equal(east.detail.length, 1)
})

test('missing comparisons, zero denominators and empty filters never retain old values', () => {
  const report = small()
  report.rows[1].prior = null
  report.rows[0].target = 0
  assert.equal(reportView(report).totals.yoy, null)
  assert.equal(reportView(report, { filters: { region: '华东' } }).totals.attainment, null)
  const empty = reportView(report, { filters: { region: '不存在' } })
  assert.equal(empty.totals.actual, null)
  assert.equal(empty.trend.length, 0)
  assert.equal(empty.detail.length, 0)
})

test('quarter and year cumulative scopes aggregate only the relevant period', () => {
  const report = small()
  report.rows.push({ date: '2026-07-01', region: '华东', sales: 50, target: 50, prior: 40 },
    { date: '2026-01-01', region: '华东', sales: 10, target: 10, prior: 10 })
  assert.equal(reportView(report, { window: 'qtd' }).totals.actual, 250)
  assert.equal(reportView(report, { window: 'ytd' }).totals.actual, 260)
})

test('sample data aggregates coherently across report surfaces', () => {
  const first = createSampleReport()
  assert.equal(first.rows.length, 1638)
  const view = reportView(first, { filters: { region: '华东' } })
  assert.equal(view.sourceRows.length, 30)
  assert.ok(Math.abs(view.detail.reduce((sum, row) => sum + row._share, 0) - 100) < 1e-8)
})

test('HTML is self contained and data cannot terminate its JSON script', () => {
  const report = createSampleReport()
  report.title = '</script><script>throw new Error("injected")</script>'
  const html = buildReportHtml(report)
  assert.ok(html.startsWith('<!DOCTYPE html>'))
  assert.ok(html.includes("connect-src 'none'"))
  assert.ok(!html.includes('<script>throw new Error'))
  assert.ok(!html.includes('https://cdn'))
  assert.ok(html.includes('JSON.parse(document.getElementById'))
})

test('SQL attainment ratios are recomputed when detail rows are aggregated', () => {
  const raw = small()
  raw.columns.push({ key: 'at_rate', label: '达成率', format: 'percent' })
  raw.rows[0].at_rate = 2
  raw.rows[1].at_rate = .75
  raw.visible_columns = ['date', 'sales', 'target', 'at_rate']
  const { report } = prepareReport(raw)
  const view = reportView(report)
  assert.ok(report.visible_columns.includes('_achievement'))
  assert.equal(view.detail.length, 1)
  assert.equal(view.detail[0]._achievement, 100)
})
