import assert from 'node:assert/strict'
import test from 'node:test'
import { exportChartOption } from '../src/utils/documentExport.js'

test('export chart configuration preserves series and axes without mutating the live chart', () => {
  const original = {
    title: { text: '业务趋势' }, legend: { textStyle: { color: '#123456' } },
    xAxis: { type: 'category', data: ['2026-09', '2026-10'] },
    yAxis: [{ type: 'value', name: '万元' }, { type: 'value', name: '%', axisLabel: { formatter: '{value}%' } }],
    series: [{ type: 'bar', data: [100, 200] }, { type: 'line', yAxisIndex: 1, data: [90, 95] }],
  }
  const exported = exportChartOption(original, true)
  assert.deepEqual(exported.series[0].data, [100, 200])
  assert.equal(exported.series[1].yAxisIndex, 1)
  assert.equal(exported.series[1].label.show, true)
  assert.equal(exported.yAxis[1].axisLabel.formatter, '{value}%')
  assert.equal(exported.animation, false)
  assert.equal(original.title.text, '业务趋势')
  assert.equal(original.series[0].label, undefined)
})
