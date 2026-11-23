import { REPORT_CSS as CSS } from './style.js'
import { reportView, reportNumber } from './model.js'

/** Standard ratios must be recomputed after grouping, never summed from SQL rows. */
export function prepareReport(raw, state = {}) {
  const aliases = {}
  const metrics = raw.metrics || {}
  const workbook = raw.source?.domain === 'workbook'
  const roleLabels = { qty: '销售数量', amount: '销售金额(CNY)', amount_usd: '销售金额(USD)',
    target: '金额目标(CNY)', target_usd: '金额目标(USD)', qty_target: '数量目标',
    prior: '同期销售金额', prior_usd: '同期销售金额(USD)', qty_prior: '同期销售数量',
    previous: '上期销售金额', previous_usd: '上期销售金额(USD)', qty_previous: '上期销售数量' }
  const sourceLabels = workbook ? {} : Object.fromEntries(Object.entries(metrics).map(([role, key]) => [key, roleLabels[role]]))
  const metricUnits = workbook ? Object.fromEntries(Object.entries(metrics).map(([role, key]) => {
    const column = raw.columns?.find(item => item.key === key)
    const monetary = column?.format === 'money' || /金额|销售额|收入|费用|成本|预算|CNY|USD/i.test(`${key} ${column?.label || ''}`)
    return [role, monetary ? (role.endsWith('usd') ? 'USD' : 'CNY') : /人数|用户|客户|访问|活跃|转化|复访/.test(`${key} ${column?.label || ''}`) ? '人' : '数量']
  })) : raw.metric_units
  const columns = [], sources = [], seen = new Set()
  for (const original of raw.columns || []) {
    const column = { ...original }
    if ((!column.label || column.label === column.key) && sourceLabels[column.key]) column.label = sourceLabels[column.key]
    if (column.format === 'percent' && !column.key.startsWith('_')) {
      const text = `${column.key} ${column.label}`.toLowerCase()
      if (/at_rate|attain|achiev|达成|完成率/.test(text) && (metrics.target || metrics.qty_target || metrics.target_usd)) aliases[column.key] = '_achievement'
      else if (/yoy|同比/.test(text) && (metrics.prior || metrics.qty_prior || metrics.prior_usd)) aliases[column.key] = '_yoy'
      else if (/qoq|mom|环比/.test(text) && (metrics.previous || metrics.qty_previous || metrics.previous_usd)) aliases[column.key] = '_qoq'
      else if (/share|占比/.test(text)) aliases[column.key] = '_share'
      if (aliases[column.key]) {
        sources.push({ ...column, label: `源数据 · ${column.label}`, format: 'text' })
        column.key = aliases[column.key]
      } else column.format = 'text'
    }
    if (!seen.has(column.key)) { columns.push(column); seen.add(column.key) }
  }
  for (const source of sources) if (!seen.has(source.key)) columns.push(source)
  const remap = values => values?.map(key => aliases[key] || key)
  return {
    report: { ...raw, metric_units: metricUnits, columns, visible_columns: remap(raw.visible_columns) },
    state: { ...state, ...(state.visible_columns ? { visible_columns: remap(state.visible_columns) } : {}) },
  }
}



/** This function is serialized into the report; keep all dependencies explicit. */
function reportRuntime(report, initialState, bridge, viewFn, numberFn) {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]))
  const root = document.getElementById('report-root')
  const palette = { navy: '#203662', red: '#c5203f', teal: '#16877f' }
  document.documentElement.style.setProperty('--navy', palette[report.accent] || palette.navy)
  let state = { ...initialState, filters: { ...(report.filters || {}), ...(initialState.filters || {}) } }
  let page = 1, sortKey = '', sortDir = -1, search = '', columnsOpen = false
  const label = key => (report.columns || []).find(column => column.key === key)?.label || key
  const post = (type, payload = {}) => { if (bridge) parent.postMessage({ type, channel: bridge, reportId: report.id, ...payload }, '*') }
  const persist = () => {
    window.__reportState = state
    post('bi-report:state', { state: { ...state, report_id: report.id, revision: report.revision } })
  }
  let measureTimer = 0
  const measure = () => {
    clearTimeout(measureTimer)
    // Browsers can suspend rAF in an offscreen sandboxed iframe. A debounced
    // timer still updates its height before the user scrolls to the report.
    measureTimer = setTimeout(() => {
      post('bi-report:resize', { height: Math.ceil(root.getBoundingClientRect().height) })
    }, 0)
  }
  const signed = value => numberFn(value, 'signed')
  const pct = value => numberFn(value, 'percent')
  const fmt = value => numberFn(value, 'compact')
  const tone = value => value == null ? 'neutral' : value >= 0 ? 'positive' : 'negative'
  const option = (value, text, selected) => `<option value="${esc(value)}" ${String(selected) === String(value) ? 'selected' : ''}>${esc(text)}</option>`
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  const canAsk = Boolean(bridge) && !report.read_only
  const pinButton = (section, title) => bridge && !report.read_only ? `<button type="button" class="pin-chart" data-pin="${section}">${title}</button>` : ''

  const monthlySource = Boolean(report.date_field) && (report.rows || []).length > 0 &&
    report.rows.every(row => /^(\d{6}|\d{4}-\d{2})$/.test(String(row[report.date_field] ?? '')))
  let counterFrame = 0
  const tooltip = document.createElement('div')
  tooltip.className = 'chart-tooltip'
  tooltip.hidden = true
  document.body.appendChild(tooltip)
  function bindChartTooltips() {
    root.querySelectorAll('.chart circle, .chart rect').forEach(el => {
      const text = el.querySelector('title')?.textContent
      if (!text) return
      const position = event => {
        const box = el.getBoundingClientRect()
        const x = event.clientX ?? box.x + box.width / 2
        const y = event.clientY ?? box.y
        tooltip.style.left = Math.max(8, Math.min(window.innerWidth - tooltip.offsetWidth - 8, x + 12)) + 'px'
        tooltip.style.top = Math.max(8, Math.min(window.innerHeight - tooltip.offsetHeight - 8, y - tooltip.offsetHeight - 12)) + 'px'
      }
      const show = event => { tooltip.textContent = text; tooltip.hidden = false; position(event) }
      el.onpointerenter = show
      el.onpointermove = position
      el.onfocus = show
      el.onpointerleave = el.onblur = () => { tooltip.hidden = true }
    })
  }
  function animateVisuals(previous) {
    if (reducedMotion.matches) return
    root.querySelectorAll('.motion-bar').forEach((el, i) => {
      el.animate([{ transform: 'scaleY(.02)', opacity: .5 }, { transform: 'scaleY(1)', opacity: 1 }], { duration: 650, delay: Math.min(i * 24, 200), easing: 'cubic-bezier(.16,1,.3,1)' })
    })
    root.querySelectorAll('.bar-fill, .contrib-fill').forEach((el, i) => {
      el.animate([{ transform: 'scaleX(.02)' }, { transform: 'scaleX(1)' }], { duration: 700, delay: i * 25, easing: 'cubic-bezier(.16,1,.3,1)' })
    })
    const parse = text => {
      const match = String(text).trim().match(/^([+−-]?)([\d,.]+)(.*)$/)
      if (!match) return null
      return { value: Number((match[1] === '−' ? '-' : match[1]) + match[2].replace(/,/g, '')), suffix: match[3], digits: (match[2].split('.')[1] || '').length, plus: match[1] === '+' }
    }
    const counters = [...root.querySelectorAll('.kpi-value')].map((el, i) => {
      const node = el.firstChild
      if (node?.nodeType !== 3) return null
      const text = node.textContent, end = parse(text), start = parse(previous[i])
      return end && Number.isFinite(end.value) ? { node, text, end, from: start?.suffix === end.suffix ? start.value : 0 } : null
    }).filter(Boolean)
    const startAt = performance.now()
    const tick = now => {
      const progress = Math.min(1, (now - startAt) / 600), eased = 1 - (1 - progress) ** 3
      counters.forEach(({ node, text, end, from }) => {
        const value = from + (end.value - from) * eased
        node.textContent = progress === 1 ? text : (end.plus && value >= 0 ? '+' : '') + value.toLocaleString('zh-CN', { minimumFractionDigits: end.digits, maximumFractionDigits: end.digits }) + end.suffix
      })
      if (progress < 1) counterFrame = requestAnimationFrame(tick)
    }
    counterFrame = requestAnimationFrame(tick)
  }
  function trendSvg(view) {
    const rows = report.date_field ? view.trend : view.groups
    const barMode = state.chart_type === 'bar' || !report.date_field
    if (!rows.length) return '<div class="chart-empty">当前筛选暂无图表数据</div>'
    const w = 900, h = 245, left = 56, right = 20, top = 22, bottom = 42
    const values = rows.flatMap(row => [row.actual, row.target]).filter(value => value != null)
    const max = Math.max(1, ...values), min = Math.min(0, ...values), span = max - min || 1
    const x = i => left + (w - left - right) * (barMode ? (i + .5) / rows.length : rows.length === 1 ? .5 : i / (rows.length - 1))
    const y = value => top + (h - top - bottom) * (1 - (value - min) / span)
    let svg = `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="实际销售与目标趋势，单位${view.unit}">`
    for (let i = 0; i <= 4; i++) {
      const value = min + span * i / 4
      svg += `<line x1="${left}" y1="${y(value)}" x2="${w - right}" y2="${y(value)}" stroke="#e7edf3" stroke-dasharray="3 5"/><text x="${left - 10}" y="${y(value) + 4}" text-anchor="end" fill="#8492a2" font-size="10">${esc(fmt(value))}</text>`
    }
    const path = field => rows.map((row, i) => row[field] == null ? '' : `${i === 0 || rows[i - 1]?.[field] == null ? 'M' : 'L'}${x(i)},${y(row[field])}`).join(' ')
    if (!barMode) {
      if (rows.every(row => row.actual != null)) svg += `<path d="${path('actual')} L${x(rows.length - 1)},${y(0)} L${x(0)},${y(0)} Z" fill="#c5203f0b"/>`
      svg += `<path d="${path('actual')}" fill="none" stroke="#c5203f" stroke-width="2.6" stroke-linejoin="round" class="draw-line" pathLength="1"/>`
    }
    if (report.date_field) svg += `<path d="${path('target')}" fill="none" stroke="#a5b4c5" stroke-width="1.6" stroke-dasharray="5 5"/>`
    const step = Math.max(1, Math.ceil(rows.length / 9))
    rows.forEach((row, i) => {
      if (row.actual != null) {
        if (barMode) {
          const width = Math.min(45, (w - left - right) / rows.length * (report.date_field ? .55 : .28))
          svg += `<rect class="motion-bar" data-motion-key="actual-${esc(row.name)}" tabindex="0" x="${x(i) - (report.date_field ? width / 2 : width + 2)}" y="${Math.min(y(row.actual), y(0))}" width="${width}" height="${Math.max(1, Math.abs(y(0) - y(row.actual)))}" rx="2" fill="#c5203f"><title>${esc(row.name)} 实际 ${esc(numberFn(row.actual))}，目标 ${esc(numberFn(row.target))}</title></rect>`
          if (!report.date_field && row.target != null) svg += `<rect class="motion-bar" data-motion-key="target-${esc(row.name)}" tabindex="0" x="${x(i) + 2}" y="${Math.min(y(row.target), y(0))}" width="${width}" height="${Math.max(1, Math.abs(y(0) - y(row.target)))}" rx="2" fill="#b4c1ce"><title>${esc(row.name)} 目标 ${esc(numberFn(row.target))}</title></rect>`
        } else svg += `<circle tabindex="0" cx="${x(i)}" cy="${y(row.actual)}" r="${rows.length > 15 ? 2.5 : 4}" fill="white" stroke="#c5203f" stroke-width="1.8"><title>${esc(row.name)} 实际 ${esc(numberFn(row.actual))}，目标 ${esc(numberFn(row.target))}</title></circle>`
      }
      if (i % step === 0 || i === rows.length - 1) svg += `<text x="${x(i)}" y="${h - 16}" text-anchor="middle" font-size="10" fill="#8492a2">${esc(row.name.replace(/^2026-/, ''))}</text>`
    })
    return svg + '</svg>'
  }
  function render(animate = true) {
    cancelAnimationFrame(counterFrame)
    const previousValues = [...root.querySelectorAll('.kpi-value')].map(el => el.firstChild?.textContent || '')
    tooltip.hidden = true
    columnsOpen = root.querySelector('.columns-editor')?.open ?? columnsOpen
    const view = viewFn(report, state)
    state.current_period = view.selected
    state.period ||= report.period || 'month'
    state.window ||= report.window || 'period'
    state.metric ||= report.metric || 'amount'
    state.dimension ||= report.dimension
    state.chart_type ||= report.chart_type || 'line'
    state.visible_columns ||= report.visible_columns || report.columns.map(column => column.key)
    const total = view.totals
    const currentFilters = Object.entries({ ...(report.filters || {}), ...state.filters }).filter(([, value]) => value)
    const workbook = report.source?.domain === 'workbook'
    const currencies = [['amount', '金额 · CNY'], ['qty', '销售数量'], ['amount_usd', '金额 · USD']].filter(([role]) => report.metrics?.[role]).map(([role, text]) => [role, workbook ? label(report.metrics[role]) : text])
    const titleUnit = workbook ? label(view.actualKey) : view.unit === '数量' ? '销售数量' : '销售金额'
    const periodLabel = `${view.selected || (report.date_field ? '全部期间' : '当前查询范围')}${({ period: '', mtd: ' · MTD', qtd: ' · QTD', ytd: ' · YTD' })[state.window] || ''}`
    const dimensions = (report.filter_fields || []).filter(key => key !== report.date_field)
    const graphRows = view.groups.slice(0, 8)
    const attainScale = Math.max(120, ...graphRows.map(row => row.attainment || 0))
    const hasPrior = total.prior != null
    const hasTarget = total.target != null
    const compareBase = hasPrior ? 'prior' : hasTarget ? 'target' : ''
    const card2 = hasTarget
      ? { label: '目标达成率', tag: 'ACT / TARGET', value: pct(total.attainment), note: `目标 ${fmt(total.target)} ${view.unit}` }
      : hasPrior ? { label: '同比增长', tag: 'VS LAST YEAR', value: signed(total.yoy), note: `同期 ${fmt(total.prior)} ${view.unit}` }
      : { label: '覆盖分组', tag: 'SCOPE', value: String(view.groups.length), note: `按${label(state.dimension)}统计` }
    const gap = total.actual == null || total.target == null ? null : total.actual - total.target
    const card3 = view.unit === '数量' && total.amount != null
      ? { label: workbook ? label(report.metrics.amount) : '销售金额', tag: workbook ? 'TOTAL' : 'CNY', value: fmt(total.amount), note: '按当前筛选汇总', tone: '' }
      : total.qty != null && (!workbook || view.actualKey !== report.metrics.qty) ? { label: workbook ? label(report.metrics.qty) : '销售数量', tag: 'VOLUME', value: fmt(total.qty), note: '按当前筛选汇总', tone: '' }
      : hasTarget ? { label: '目标差额', tag: 'ACT − TARGET', value: fmt(gap), note: `实际减目标 · ${view.unit}`, tone: tone(gap) }
      : { label: '最大分组贡献', tag: 'TOP SHARE', value: pct(total.actual ? view.groups[0]?.actual / total.actual * 100 : null), note: view.groups[0]?.name || '暂无匹配数据', tone: '' }
    const belowTarget = view.groups.filter(row => row.attainment != null && row.attainment < 100).length
    const card4 = total.previous != null
      ? { label: '环比增长', tag: 'VS PREVIOUS', value: signed(total.qoq), tone: tone(total.qoq), note: `上期 ${fmt(total.previous)} ${view.unit}` }
      : hasPrior ? { label: '同比增长', tag: 'VS LAST YEAR', value: signed(total.yoy), tone: tone(total.yoy), note: `同期 ${fmt(total.prior)} ${view.unit}` }
      : hasTarget ? { label: '未达目标分组', tag: 'BELOW TARGET', value: String(belowTarget), tone: belowTarget ? 'negative' : 'positive', note: `按${label(state.dimension)}统计 · 共${view.groups.length}组` }
      : { label: '对比分组数', tag: 'SCOPE', value: String(view.groups.length), tone: '', note: `按${label(state.dimension)}统计` }
    const contribution = row => compareBase ? row.actual == null || row[compareBase] == null ? null : row.actual - row[compareBase] : row.actual
    const maxContribution = Math.max(1, ...graphRows.map(row => Math.abs(contribution(row) || 0)))
    const sourceNotice = report.source?.truncated ? '<div class="notice">查询结果已截断。以下图表和指标仅代表当前返回样本，请缩小范围后重新查询，或使用完整结果导出。</div>' : ''
    const tableRows = view.detail.filter(row => !search || Object.values(row).some(value => String(value ?? '').toLowerCase().includes(search.toLowerCase())))
    if (sortKey) tableRows.sort((a, b) => {
      if (a[sortKey] == null) return 1
      if (b[sortKey] == null) return -1
      return (typeof a[sortKey] === 'number' && typeof b[sortKey] === 'number' ? a[sortKey] - b[sortKey] : String(a[sortKey]).localeCompare(String(b[sortKey]), 'zh-CN')) * sortDir
    })
    const pageCount = Math.max(1, Math.ceil(tableRows.length / 10))
    page = Math.min(page, pageCount)
    const allColumns = [...report.columns]
    for (const [key, text] of [['_achievement', '达成率'], ['_yoy', '同比增长'], ['_qoq', '环比增长'], ['_share', workbook ? '指标占比' : '销售占比']]) if (!allColumns.some(c => c.key === key)) allColumns.push({ key, label: text, format: 'percent' })
    const visible = allColumns.filter(column => state.visible_columns.includes(column.key))
    const cell = (row, column) => column.key.startsWith('_') || column.format === 'percent' ? pct(row[column.key]) : ['number', 'money'].includes(column.format) || typeof row[column.key] === 'number' ? numberFn(row[column.key], column.format) : String(row[column.key] ?? '—')
    const isNumeric = column => column.key.startsWith('_') || ['number', 'money', 'percent'].includes(column.format) || Object.values(report.metrics || {}).includes(column.key)
    const legendPeriods = { day: '按日', month: '按月', quarter: '按季度', year: '按年度' }
    const summary = !view.sourceRows.length ? '当前筛选没有匹配数据。请调整期间或筛选条件。' : `${periodLabel}，${titleUnit}${fmt(total.actual)}${view.unit === '数量' ? '' : ` ${view.unit}`}，${total.attainment == null ? '当前数据未提供可比目标' : `目标达成率 ${pct(total.attainment)}`}。${view.groups[0] ? `${label(state.dimension)}中，${view.groups[0].name}${workbook ? '指标' : '销售'}贡献最高，占比 ${pct(total.actual ? view.groups[0].actual / total.actual * 100 : null)}。` : ''}${hasPrior ? `同比 ${signed(total.yoy)}，增量贡献以各分组本期减同期计算。` : hasTarget ? '目标差额贡献按各分组实际减目标计算。' : '未提供同期或目标，贡献图展示销售结构。'}`
    root.innerHTML = `<article class="report">
      <header class="masthead"><div class="mast-top"><div class="wordmark"><svg class="brand-svg" viewBox="0 0 30 30" fill="none" aria-hidden="true"><path d="M3 24V16H8V24M12 24V10H17V24M21 24V4H26V24" stroke="white" stroke-width="3"/><path d="M2 9L10 3" stroke="#e6606d" stroke-width="3"/></svg>GILEAD · BUSINESS INTELLIGENCE</div><span class="badge">${(report.source?.demo || report.source?.sample) ? '样例业务数据' : '已核验查询数据'}</span></div><h1>${esc(report.title)}</h1><p>${esc(report.subtitle || '从商业表现到行动建议，让每一项判断都有数据依据。')}</p><div class="mast-meta"><span>报告期间 <b>${esc(periodLabel)}</b></span><span>数据记录 <b>${view.sourceRows.length.toLocaleString()} 条</b></span><span>报告版本 <b>v${Number(report.revision) || 1}</b></span></div></header>
      <div class="toolbar"><div class="toolbar-left">${report.date_field ? `<label>分析视图</label><div class="seg">${Object.entries(legendPeriods).map(([value, text]) => `<button type="button" data-period="${value}" class="${state.period === value ? 'on' : ''}" aria-pressed="${state.period === value}">${text}</button>`).join('')}</div>` : `<label>对比视角</label><strong style="font-size:12px">按${esc(label(state.dimension))}分析</strong>`}</div><div class="toolbar-right">${pinButton('report','＋ 加入看板')}<button type="button" id="csv-export">↓ 导出数据</button><button type="button" id="html-export">↓ 下载 HTML</button><button type="button" id="print-report">打印</button></div></div>
      <div class="filter-panel">${report.date_field ? `<div class="field"><label for="period-select">统计月份</label><select id="period-select">${view.periods.map(value => option(value, value, view.selected)).join('') || option('', '未提供日期', '')}</select></div><div class="field"><label for="window-select">累计范围</label><select id="window-select">${[['period', '当月'], ['mtd', '月度累计 MTD'], ['qtd', '季度累计 QTD'], ['ytd', '年度累计 YTD']].map(([v, t]) => option(v, t, state.window)).join('')}</select></div>` : ''}${(report.filter_fields || []).map(key => `<div class="field"><label for="filter-${esc(key)}">${esc(label(key))}</label><select id="filter-${esc(key)}" data-filter="${esc(key)}">${option('', '全部' + label(key), state.filters[key] ?? report.filters?.[key] ?? '')}${(view.filterOptions[key] || []).map(value => option(value, value, state.filters[key] ?? report.filters?.[key])).join('')}</select></div>`).join('')}<button class="reset" id="reset-filters" type="button">重置筛选</button></div>
      ${sourceNotice}<p class="filter-state">${currentFilters.length ? `已筛选：${currentFilters.map(([key, value]) => `${esc(label(key))} · ${esc(value)}`).join('　/　')}` : '当前范围：本次查询结果'}　·　所有指标、图表与明细同步更新</p>
      <div class="pin-kpis">${pinButton('kpis','＋ 保存指标卡')}</div><section class="kpis" aria-label="关键指标"><div class="kpi primary"><div class="kpi-label">${titleUnit}<i>${view.unit}</i></div><div class="kpi-value">${esc(fmt(total.actual))}<small>${view.unit === '数量' ? '单位' : view.unit}</small></div><div class="kpi-note">${hasPrior ? `<span class="${tone(total.yoy)}">${esc(signed(total.yoy))}</span> 同比增长` : '按当前筛选汇总'}</div></div><div class="kpi"><div class="kpi-label">${esc(card2.label)}<i>${esc(card2.tag)}</i></div><div class="kpi-value">${esc(card2.value)}</div><div class="kpi-note">${esc(card2.note)}</div></div><div class="kpi"><div class="kpi-label">${esc(card3.label)}<i>${esc(card3.tag)}</i></div><div class="kpi-value ${card3.tone}">${esc(card3.value)}</div><div class="kpi-note">${esc(card3.note)}</div></div><div class="kpi"><div class="kpi-label">${esc(card4.label)}<i>${esc(card4.tag)}</i></div><div class="kpi-value ${card4.tone}">${esc(card4.value)}</div><div class="kpi-note">${esc(card4.note)}</div></div></section>
      <div class="section-heading"><h2>商业表现总览<span>PERFORMANCE OVERVIEW</span></h2><select id="metric-select" aria-label="指标口径">${currencies.map(([v, t]) => option(v, t, state.metric)).join('')}</select></div>
      <section class="panel"><div class="panel-head"><div><h3>${report.date_field ? '实际与目标趋势' : `${esc(label(state.dimension))}实际与目标对比`}</h3><p>${report.date_field ? legendPeriods[state.period] + '聚合' : '当前查询范围'} · ${esc(periodLabel)} · ${view.unit}</p></div><div class="seg"><button type="button" data-chart="line" class="${state.chart_type === 'line' ? 'on' : ''}">折线</button><button type="button" data-chart="bar" class="${state.chart_type === 'bar' ? 'on' : ''}">柱状</button></div>${pinButton('trend','＋ 保存趋势图')}</div><div class="legend"><span><i></i>实际销售</span><span><i class="target"></i>目标销售</span></div>${trendSvg(view)}</section>
      <div class="two-col"><section class="panel"><div class="panel-head"><div><h3>${esc(label(state.dimension))}达成对比</h3><p>点击名称下钻 · 参考线为 100% 目标</p></div><select id="dimension-select" aria-label="对比维度">${[...new Set([report.dimension, ...dimensions])].map(value => option(value, label(value), state.dimension)).join('')}</select></div>${graphRows.length ? graphRows.map(row => `<div class="bar-row"><div class="bar-label"><button type="button" data-drill="${esc(row.name)}">${esc(row.name)} ↗</button><strong class="${row.attainment != null && row.attainment < 100 ? 'negative' : ''}">${esc(pct(row.attainment))}</strong></div><div class="bar-track"><div class="bar-fill ${row.attainment != null && row.attainment < 100 ? 'low' : ''}" style="width:${Math.max(0, Math.min(100, (row.attainment || 0) / attainScale * 100))}%"></div><i class="goal" style="left:${100 / attainScale * 100}%"></i></div><div class="bar-sub">实际 ${esc(fmt(row.actual))} / 目标 ${esc(fmt(row.target))} ${view.unit}</div></div>`).join('') : '<div class="chart-empty">当前筛选暂无数据</div>'}</section><section class="panel"><div class="panel-head"><div><h3>${hasPrior ? '同比增量贡献' : hasTarget ? '目标差额贡献' : '销售贡献结构'}</h3><p>${hasPrior ? '本期 − 同期 · 正负贡献可相加' : hasTarget ? '实际 − 目标 · 正负贡献可相加' : '未提供可比基数，按实际销售展示'} · ${view.unit}</p></div><span class="badge" style="border-color:var(--line);color:var(--muted)">${esc(label(state.dimension))}</span>${pinButton('contribution','＋ 保存贡献图')}</div>${graphRows.length ? graphRows.map(row => { const value = contribution(row); const width = Math.abs(value || 0) / maxContribution * 48; return `<div class="contrib"><span>${esc(row.name)}</span><div class="contrib-plot"><div class="contrib-fill ${value < 0 ? 'neg' : ''}" style="left:${value < 0 ? 50 - width : 50}%;width:${width}%"></div></div><strong class="${tone(value)}">${value > 0 ? '+' : ''}${esc(fmt(value))}</strong></div>` }).join('') : '<div class="chart-empty">当前筛选暂无数据</div>'}<p class="bar-sub" style="margin-top:20px">${compareBase ? '青色为正向贡献，红色为负向贡献。' : '贡献值来自当前筛选结果。'}${view.groups.length > 8 ? '图中显示前8项，其余见明细。' : ''}</p></section></div>
      <div class="insight-summary" role="status">${esc(summary)}</div>
      ${view.sourceRows.length && (report.findings || []).length ? `<div class="section-heading"><h2>洞察与行动<span>INSIGHTS & ACTIONS</span></h2><span>基于报告生成时的分析范围</span></div><div class="findings">${report.findings.map((item, i) => `<section class="finding"><span class="num">0${i + 1}</span><span class="finding-type">${esc(({ fact: '已核验事实', evidence: '数据证据', conclusion: '分析结论', hypothesis: '待验证假设', suggestion: '行动建议', action: '行动建议', risk: '关注事项', info: '业务观察' })[item.type] || '分析结论')}</span><h3>${esc(item.title)}</h3><p>${esc(item.body)}</p></section>`).join('')}</div>${currentFilters.length ? '<p class="bar-sub">筛选后的结论见上方动态摘要；如需重新归因，请在下方追问。</p>' : ''}` : ''}
      <div class="section-heading"><h2>数据明细<span>DETAIL EXPLORER</span></h2><span>聚合口径与图表保持一致</span></div><section class="panel table-panel"><div class="table-tools"><h3>${esc(report.date_field ? legendPeriods[state.period] : '当前范围')}明细<small>${tableRows.length} 条聚合记录</small></h3><input id="table-search" aria-label="搜索明细" placeholder="搜索当前明细…" value="${esc(search)}" /></div><div class="table-scroll"><table><thead><tr>${visible.map(column => `<th tabindex="0" data-sort="${esc(column.key)}" class="${isNumeric(column) ? 'numeric' : ''}" aria-sort="${sortKey === column.key ? sortDir === 1 ? 'ascending' : 'descending' : 'none'}">${esc(column.label)} ${sortKey === column.key ? sortDir === 1 ? '↑' : '↓' : '↕'}</th>`).join('')}</tr></thead><tbody>${tableRows.slice((page - 1) * 10, page * 10).map(row => `<tr>${visible.map(column => `<td class="${isNumeric(column) ? 'numeric' : ''}">${esc(cell(row, column))}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${Math.max(1, visible.length)}"><div class="empty"><strong>当前筛选暂无数据</strong>请调整筛选条件或清空搜索</div></td></tr>`}</tbody></table></div><div class="pager"><span>共 ${tableRows.length} 条 · 每页 10 条</span><div><button id="prev-page" type="button" ${page === 1 ? 'disabled' : ''}>‹</button><span>${page} / ${pageCount}</span><button id="next-page" type="button" ${page >= pageCount ? 'disabled' : ''}>›</button></div></div><details class="columns-editor" ${columnsOpen ? 'open' : ''}><summary>编辑显示字段 · ${visible.length} 个已选</summary><div class="columns-list">${allColumns.map(column => `<label><input type="checkbox" data-column="${esc(column.key)}" ${state.visible_columns.includes(column.key) ? 'checked' : ''}>${esc(column.label)}</label>`).join('')}</div></details></section>
      <section class="followup"><div><strong>用自然语言继续分析</strong><p>${canAsk ? '保留当前筛选，继续下钻或调整报告' : report.read_only ? '已保存的看板快照；智能修改请回到原业务对话' : '此文件支持离线交互；智能修改请回到应用对话'}</p></div><div id="followup-form" role="group" aria-label="继续分析"><input id="followup-input" aria-label="报告修改要求" placeholder="例如：新增省份字段，改为柱状图" ${canAsk ? '' : 'disabled'} /><button type="button" ${canAsk ? '' : 'disabled'}>修改报告 ↗</button></div></section>
      <footer class="footer"><div><strong>${esc(report.source?.label || '查询结果')}</strong><br>${(report.source?.demo || report.source?.sample) ? '样例业务数据，非真实业务结果。' : '仅在已授权返回结果内筛选；扩大范围或新增源字段须重新查询。'}<br>${esc(report.source?.note || '比率按汇总分子/分母重算；缺失或零比较基数显示“—”。')}</div><div>GILEAD AI4BI · REPORT v${Number(report.revision) || 1}<br>${view.sourceRows.length.toLocaleString()} 条源记录 · ${esc(view.unit)}<br>交互筛选 / 字段编辑 / 自然语言追问</div></footer>
    </article>`
    root.querySelectorAll('[data-period]').forEach(el => {
      if (el.dataset.period === 'day' && monthlySource) {
        el.title = canAsk ? '按日分析会补查日粒度纯销数据' : '当前为月度数据；按日分析请回到应用补查日明细'
        el.disabled = !canAsk
        el.onclick = () => post('bi-report:ask', { text: '改为按日查看当前报告，请补查日粒度纯销数据，保留当前筛选与统计月份；目标和同比只展示已取得的可比数据。', state: { ...state, period: 'day' } })
      } else el.onclick = () => change({ period: el.dataset.period })
    })
    root.querySelectorAll('[data-pin]').forEach(el => el.onclick = () => post('bi-report:pin', { section: el.dataset.pin, state }))
    root.querySelectorAll('[data-chart]').forEach(el => el.onclick = () => change({ chart_type: el.dataset.chart }))
    root.querySelectorAll('[data-filter]').forEach(el => el.onchange = () => change({ filters: { ...state.filters, [el.dataset.filter]: el.value } }))
    root.querySelectorAll('[data-drill]').forEach(el => el.onclick = () => change({ filters: { ...state.filters, [state.dimension]: el.dataset.drill } }))
    for (const [id, key] of [['period-select', 'current_period'], ['window-select', 'window'], ['metric-select', 'metric'], ['dimension-select', 'dimension']]) { const control = root.querySelector(`#${id}`); if (control) control.onchange = event => change({ [key]: event.target.value }) }
    root.querySelector('#reset-filters').onclick = () => change({ filters: Object.fromEntries((report.filter_fields || []).map(key => [key, ''])), current_period: report.current_period || view.periods.at(-1), window: report.window || 'period' })
    root.querySelectorAll('[data-column]').forEach(el => el.onchange = () => {
      const selected = [...root.querySelectorAll('[data-column]:checked')].map(input => input.dataset.column)
      if (!selected.length) { el.checked = true; return }
      change({ visible_columns: selected })
    })
    const doSort = el => { sortDir = sortKey === el.dataset.sort ? -sortDir : -1; sortKey = el.dataset.sort; render(false) }
    root.querySelectorAll('[data-sort]').forEach(el => { el.onclick = () => doSort(el); el.onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); doSort(el) } } })
    root.querySelector('#table-search').oninput = event => { const pos = event.target.selectionStart; search = event.target.value; page = 1; render(false); const input = root.querySelector('#table-search'); input.focus(); input.setSelectionRange(pos, pos) }
    root.querySelector('#prev-page').onclick = () => { page--; render(false) }
    root.querySelector('#next-page').onclick = () => { page++; render(false) }
    root.querySelector('.columns-editor').ontoggle = event => { columnsOpen = event.target.open; measure() }
    root.querySelector('#print-report').onclick = () => bridge ? post('bi-report:print') : window.print()
    root.querySelector('#html-export').onclick = () => {
      if (bridge) { post('bi-report:download', { state }); return }
      // Keep the complete original runtime and embed the current state for a new offline copy.
      const clone = document.documentElement.cloneNode(true)
      clone.querySelector('#report-initial-state').textContent = JSON.stringify(state).replace(/</g, '\\u003c')
      clone.querySelector('#report-root').innerHTML = ''
      download(`${report.title}.html`, '<!DOCTYPE html>\n' + clone.outerHTML, 'text/html;charset=utf-8')
    }
    root.querySelector('#csv-export').onclick = () => {
      const quote = value => { let text = String(value ?? ''); if (/^[=+@\-\t\r]/.test(text)) text = "'" + text; return '"' + text.replace(/"/g, '""') + '"' }
      const csv = '\ufeff' + [visible.map(column => quote(column.label)).join(','), ...tableRows.map(row => visible.map(column => quote(cell(row, column))).join(','))].join('\r\n')
      download(`${report.title}.csv`, csv, 'text/csv;charset=utf-8')
    }
    const sendFollowup = () => {
      const text = root.querySelector('#followup-input').value.trim()
      if (text && canAsk) post('bi-report:ask', { text, state })
    }
    // The iframe intentionally has no allow-forms capability. Use the authenticated
    // message bridge for both click and Enter, without native form submission.
    root.querySelector('#followup-form button').onclick = sendFollowup
    root.querySelector('#followup-input').onkeydown = event => {
      if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); sendFollowup() }
    }
    bindChartTooltips()
    if (animate) animateVisuals(previousValues)
    persist(); measure()
  }
  function change(patch) { const focusId = document.activeElement?.id; const column = document.activeElement?.dataset.column; state = { ...state, ...patch }; page = 1; render(!patch.visible_columns); if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true }); else if (column) [...root.querySelectorAll('[data-column]')].find(el => el.dataset.column === column)?.focus({ preventScroll: true }) }
  function download(filename, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  window.addEventListener('resize', measure)
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(measure).observe(root)
  render()
}

export function buildReportHtml(report, { state = {}, bridge = '' } = {}) {
  const prepared = prepareReport(report, state)
  report = prepared.report
  state = prepared.state
  const safeJson = value => JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029')
  const title = String(report.title || '商业分析报告').replace(/[<>&"]/g, '')
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'"><title>${title}</title><style>${CSS}</style></head><body><main id="report-root"></main><script type="application/json" id="report-data">${safeJson(report)}</script><script type="application/json" id="report-initial-state">${safeJson(state)}</script><script>(${reportRuntime.toString()})(JSON.parse(document.getElementById('report-data').textContent),JSON.parse(document.getElementById('report-initial-state').textContent),${safeJson(bridge)},${reportView.toString()},${reportNumber.toString()});<\/script></body></html>`
}
