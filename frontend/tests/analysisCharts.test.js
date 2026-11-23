import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisCsv, chartDataFor, formatChartCell, kpiDisplay, sortChartRows } from '../src/utils/analysisCharts.js'

test('KPI formatting keeps fractions, exact totals and unavailable values distinct', () => {
  assert.deepEqual(kpiDisplay({ value: .45, unit: '%' }), { value: '45', unit: '%', exact: '45.00%' })
  assert.equal(kpiDisplay({ value: .9695198983, unit: '%' }).value, '96.95')
  assert.deepEqual(kpiDisplay({ value: 1234567.89, unit: '元' }), { value: '123.46', unit: '万元', exact: '1,234,567.89元' })
  assert.equal(kpiDisplay({ value: null, note: '需要总体查询' }).value, '—')
  assert.equal(kpiDisplay({ value: 0, unit: '家' }).value, '0')
})

test('table percentage formats support fraction and explicit percentage source data', () => {
  const data = { formats: { 达成率: { percent: true }, 同比: { percent: true, scale: 'percent' } } }
  assert.equal(formatChartCell(.875, '达成率', data), '87.5%')
  assert.equal(formatChartCell(12.3, '同比', data), '12.3%')
  assert.equal(formatChartCell(null, '销售金额', data), '—')
  assert.equal(formatChartCell('北京', '城市', data), '北京')
})

test('chart data follows view-specific data with a legacy fallback', () => {
  const data = { columns: ['城市', '金额'], rows: [['北京', 10]] }
  const specific = { columns: ['城市', '金额', '累计贡献率'], rows: [['北京', 10, 1]] }
  assert.equal(chartDataFor({ data }, { data: specific }), specific)
  assert.equal(chartDataFor({ data }, {}), data)
  assert.deepEqual(chartDataFor({}, { option: { xAxis: { type: 'category', data: ['北京'] }, series: [{ name: '金额', type: 'bar', data: [10] }] } }),
    { columns: ['类别', '金额'], rows: [['北京', 10]], row_count: 1 })
})

test('sorting is numeric, keeps missing values last and does not mutate source rows', () => {
  const rows = [['北京', 10], ['上海', 2], ['广州', null]]
  assert.deepEqual(sortChartRows(rows, 1).map(row => row[0]), ['上海', '北京', '广州'])
  assert.deepEqual(sortChartRows(rows, 1, -1).map(row => row[0]), ['北京', '上海', '广州'])
  assert.equal(rows[0][0], '北京')
})

test('historical charts always expose data, including implicit axes and matrix plots', () => {
  const old = chartDataFor({}, { option: { xAxis: { data: ['北京'] }, series: [{ type: 'bar', data: [10] }] } })
  assert.deepEqual(old.rows, [['北京', 10]])
  const heatmap = chartDataFor({}, { option: { xAxis: { data: ['2026-01'] }, yAxis: { data: ['北京'] }, series: [{ type: 'heatmap', data: [[0, 0, 10]] }] } })
  assert.deepEqual(heatmap.rows, [['2026-01', '北京', 10]])
  const scatter = chartDataFor({}, { option: { series: [{ type: 'scatter', data: [{ name: '北京', value: [10, .5] }] }] } })
  assert.deepEqual(scatter.rows, [['北京', 10, .5]])
  assert.deepEqual(chartDataFor({}, { option: {} }).rows, [])
})

test('CSV retains percentage units and escapes formulas, commas and quotes', () => {
  const csv = analysisCsv({ columns: ['名称', '达成率', '金额'],
    formats: { 达成率: { percent: true } }, rows: [[' =HYPERLINK("x")', .5, -1], ['北京,上海', 1, 2]] })
  assert.ok(csv.startsWith('\uFEFF'))
  assert.ok(csv.includes('"\' =HYPERLINK(""x"")"'))
  assert.ok(csv.includes('"50%","-1"'))
  assert.ok(csv.includes('"北京,上海"'))
})
