function numeric(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null
  const parsed = typeof value === 'number' ? value : Number(String(value).replaceAll(',', ''))
  return Number.isFinite(parsed) ? parsed : null
}

export function kpiDisplay(metric) {
  const value = numeric(metric.value)
  if (value === null) return { value: '—', unit: '', exact: metric.note || '暂无可用数据' }
  if (metric.unit === '%') {
    return { value: (value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 }), unit: '%', exact: `${(value * 100).toFixed(2)}%` }
  }
  const scale = Math.abs(value) >= 1e8 ? 1e8 : Math.abs(value) >= 1e4 ? 1e4 : 1
  const suffix = scale === 1e8 ? '亿' : scale === 1e4 ? '万' : ''
  return {
    value: (value / scale).toLocaleString('zh-CN', { maximumFractionDigits: 2 }),
    unit: `${suffix}${metric.unit || ''}`,
    exact: `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${metric.unit || ''}`,
  }
}

export function formatChartCell(value, column, data) {
  if (value === null || value === undefined || value === '') return '—'
  const format = data?.formats?.[column] || {}
  const parsed = numeric(value)
  if (format.percent && parsed !== null) {
    const factor = format.scale === 'percent' ? 1 : 100
    return `${(parsed * factor).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`
  }
  return typeof value === 'number'
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : String(value)
}

export function chartDataFor(bundle, chart) {
  if (chart?.data?.columns?.length) return chart.data
  if (bundle?.data?.columns?.length) return bundle.data
  const option = chart?.option || {}
  const series = option.series || []
  const x = [option.xAxis].flat().filter(Boolean)[0] || {}
  const y = [option.yAxis].flat().filter(Boolean)[0] || {}
  if (series[0]?.type === 'heatmap') {
    const rows = (series[0].data || []).map(point => [x.data?.[point[0]], y.data?.[point[1]], point[2]])
    return { columns: [x.name || '横轴', y.name || '纵轴', '数值'], rows, row_count: rows.length }
  }
  if (series[0]?.type === 'radar') {
    const rows = series.flatMap(item => (item.data || []).map(point => [point.name, ...(point.value || [])]))
    return { columns: ['类别', ...(option.radar?.indicator || []).map(item => item.name)], rows, row_count: rows.length }
  }
  if (series[0]?.type === 'pie') {
    const rows = (series[0].data || []).map(item => [item.name, item.value])
    return { columns: ['类别', '数值'], rows, row_count: rows.length }
  }
  const axes = [option.xAxis, option.yAxis].flat().filter(Boolean)
  const category = axes.find(axis => axis.data?.length)
  if (!category || !series.length) {
    const rows = series.flatMap(item => (item.data || []).map((point, index) => {
      const value = point && typeof point === 'object' && !Array.isArray(point) ? point.value : point
      return [point?.name || String(index + 1), ...(Array.isArray(value) ? value : [value])]
    }))
    const width = Math.max(1, ...rows.map(row => row.length - 1))
    const values = width === 1 ? ['数值'] : [x.name || 'X', y.name || 'Y', ...Array.from({ length: Math.max(0, width - 2) }, (_, index) => `数值${index + 3}`)]
    return { columns: ['类别', ...values], rows, row_count: rows.length }
  }
  const columns = ['类别', ...series.map((item, index) => item.name || `指标${index + 1}`)]
  const rows = category.data.map((name, index) => [name, ...series.map(item => {
    const point = item.data?.[index]
    return point && typeof point === 'object' && !Array.isArray(point) ? point.value : point
  })])
  return { columns, rows, row_count: rows.length }
}

export function analysisCsv(data) {
  function escape(value) {
    let text = value === null || value === undefined ? '' : String(value)
    if (typeof value === 'string' && /^\s*[=+@\-\t\r]/.test(text)) text = `'${text}`
    return `"${text.replaceAll('"', '""')}"`
  }
  const lines = [data.columns.map(escape).join(',')]
  for (const row of data.rows || []) {
    lines.push(data.columns.map((column, index) => {
      const format = data.formats?.[column]
      const value = row[index]
      if (format?.percent && typeof value === 'number') {
        return escape(`${value * (format.scale === 'percent' ? 1 : 100)}%`)
      }
      return escape(value)
    }).join(','))
  }
  return `\uFEFF${lines.join('\r\n')}`
}

export function sortChartRows(rows, columnIndex, direction = 1) {
  if (columnIndex < 0) return rows
  return [...rows].sort((left, right) => {
    const a = left[columnIndex], b = right[columnIndex]
    if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1
    if (b === null || b === undefined) return -1
    const comparison = typeof a === 'number' && typeof b === 'number'
      ? a - b
      : String(a).localeCompare(String(b), 'zh-CN', { numeric: true })
    return direction * comparison
  })
}
