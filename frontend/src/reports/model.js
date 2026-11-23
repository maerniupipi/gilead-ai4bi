/** Pure calculations shared by the in-app and downloaded HTML report. */
export function reportView(report, state = {}) {
  const metrics = report.metrics || {}
  const config = { ...report, ...state, filters: { ...(report.filters || {}), ...(state.filters || {}) } }
  const parseDate = value => {
    const raw = String(value ?? '').replace(/^(\d{4})(\d{2})$/, '$1-$2-01')
    const date = new Date(/^\d{4}-\d{2}$/.test(raw) ? `${raw}-01T00:00:00Z` : raw)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const dates = (report.rows || []).map(row => parseDate(row[report.date_field])).filter(Boolean)
  const latest = dates.length ? new Date(Math.max(...dates.map(date => date.getTime()))) : null
  const selected = config.current_period || latest?.toISOString().slice(0, 7) || ''
  const anchor = parseDate(selected)
  const year = anchor?.getUTCFullYear()
  const month = anchor?.getUTCMonth()
  const sourceRows = (report.rows || []).filter(row => {
    if (Object.entries(config.filters).some(([key, value]) => value && String(row[key] ?? '') !== value)) return false
    if (!report.date_field || !anchor) return true
    const date = parseDate(row[report.date_field])
    if (!date || date.getUTCFullYear() !== year) return false
    const rowMonth = date.getUTCMonth()
    if (config.window === 'ytd') return rowMonth <= month
    if (config.window === 'qtd') return Math.floor(rowMonth / 3) === Math.floor(month / 3) && rowMonth <= month
    return rowMonth === month
  })
  const sum = (rows, key) => {
    if (!key || !rows.length) return null
    let total = 0
    for (const row of rows) {
      if (row[key] === null || row[key] === undefined || row[key] === '') return null
      const value = Number(row[key])
      if (!Number.isFinite(value)) return null
      total += value
    }
    return total
  }
  const ratio = (a, b, growth = false) => a == null || b == null || b === 0 ? null : (a / b - (growth ? 1 : 0)) * 100
  const preferred = config.metric === 'qty' ? 'qty' : config.metric === 'amount_usd' ? 'amount_usd' : 'amount'
  const role = metrics[preferred] ? preferred : ['amount', 'qty', 'amount_usd'].find(key => metrics[key]) || preferred
  const targetKey = metrics[role === 'qty' ? 'qty_target' : role === 'amount_usd' ? 'target_usd' : 'target']
  const priorKey = metrics[role === 'qty' ? 'qty_prior' : role === 'amount_usd' ? 'prior_usd' : 'prior']
  const previousKey = metrics[role === 'qty' ? 'qty_previous' : role === 'amount_usd' ? 'previous_usd' : 'previous']
  const actualKey = metrics[role]
  const summarize = rows => {
    const actual = sum(rows, actualKey)
    const target = sum(rows, targetKey)
    const prior = sum(rows, priorKey)
    const previous = sum(rows, previousKey)
    return { actual, target, prior, previous, qty: sum(rows, metrics.qty), amount: sum(rows, metrics.amount),
      attainment: ratio(actual, target), yoy: ratio(actual, prior, true), qoq: ratio(actual, previous, true) }
  }
  const totals = summarize(sourceRows)
  const group = (rows, keyFn) => {
    const groups = new Map()
    for (const row of rows) {
      const key = keyFn(row)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(row)
    }
    return [...groups].map(([name, values]) => ({ name, ...summarize(values), rows: values }))
  }
  const dateLabel = row => {
    const date = parseDate(row[report.date_field])
    if (!date) return report.date_field ? '未提供日期' : selected || '当前期间'
    const value = date.toISOString().slice(0, 10)
    if (config.period === 'day') return value
    if (config.period === 'quarter') return `${date.getUTCFullYear()} Q${Math.floor(date.getUTCMonth() / 3) + 1}`
    return config.period === 'year' ? value.slice(0, 4) : value.slice(0, 7)
  }
  const trend = group(sourceRows, dateLabel).sort((a, b) => a.name.localeCompare(b.name))
  const groups = group(sourceRows, row => String(row[config.dimension] ?? '未分类'))
    .sort((a, b) => (b.actual || 0) - (a.actual || 0))
  const columns = report.columns || []
  const numericKeys = new Set([...Object.values(metrics), ...columns.filter(c => ['number', 'money', 'percent'].includes(c.format)).map(c => c.key)])
  const visible = config.visible_columns || columns.map(column => column.key)
  const detailDims = visible.filter(key => !numericKeys.has(key) && !key.startsWith('_'))
  const detailGroups = group(sourceRows, row => JSON.stringify(detailDims.map(key => key === report.date_field ? dateLabel(row) : row[key])))
  const detail = detailGroups.map(item => {
    const row = { ...item.rows[0] }
    for (const key of numericKeys) row[key] = sum(item.rows, key)
    if (report.date_field) row[report.date_field] = dateLabel(item.rows[0])
    row._achievement = item.attainment
    row._yoy = item.yoy
    row._qoq = item.qoq
    row._share = metrics.amount ? ratio(item.amount, totals.amount) : ratio(item.actual, totals.actual)
    return row
  })
  return { config, selected, sourceRows, totals, trend, groups, detail, actualKey,
    unit: report.metric_units?.[role] || (role === 'qty' ? '数量' : role === 'amount_usd' ? 'USD' : 'CNY'),
    periods: [...new Set(dates.map(date => date.toISOString().slice(0, 7)))].sort(),
    filterOptions: Object.fromEntries((report.filter_fields || []).map(key => [key,
      [...new Set((report.rows || []).map(row => String(row[key] ?? '')))].filter(Boolean).sort()])),
  }
}

export function reportNumber(value, style = 'number') {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  if (style === 'percent') return `${n.toFixed(1)}%`
  if (style === 'signed') return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
  if (style === 'compact' && Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (style === 'compact' && Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toLocaleString('zh-CN', { maximumFractionDigits: style === 'money' ? 2 : 6 })
}
