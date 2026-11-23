import { yieldToBrowser } from './rendering.js'

export function exportChartOption(raw, showValues = false) {
  const replacements = { '#193d60': '#c5203f', '#112b46': '#881222', '#b33a52': '#3fb9c2' }
  const option = JSON.parse(JSON.stringify(raw, (_key, value) =>
    typeof value === 'string' ? (replacements[value.toLowerCase()] || value) : value))
  option.animation = false
  option.backgroundColor = '#ffffff'
  option.title = { show: false }
  option.textStyle = { ...(option.textStyle || {}), fontFamily: 'Inter, system-ui, PingFang SC, Microsoft YaHei, sans-serif', fontSize: 18 }
  option.tooltip = { show: false }
  delete option.toolbox
  if (!option.color?.length) option.color = ['#c5203f', '#203662', '#3fb9c2', '#94a3b8', '#dca965']
  if (option.legend) option.legend.textStyle = { ...option.legend.textStyle, fontSize: 18 }
  for (const key of ['xAxis', 'yAxis']) {
    for (const axis of [option[key]].flat().filter(Boolean)) {
      axis.axisLabel = { ...axis.axisLabel, fontSize: 17, hideOverlap: true }
      axis.nameTextStyle = { ...axis.nameTextStyle, fontSize: 18 }
      if (axis.type === 'value' && !axis.axisLabel.formatter) {
        axis.axisLabel.formatter = value => Math.abs(value) >= 1e8
          ? `${Number((value / 1e8).toFixed(1))}亿`
          : Math.abs(value) >= 1e4 ? `${Number((value / 1e4).toFixed(1))}万` : Number(value).toLocaleString('zh-CN')
      }
    }
  }
  for (const series of option.series || []) {
    series.animation = false
    series.label = { ...series.label, show: showValues, fontSize: 16 }
    series.labelLayout = { ...series.labelLayout, hideOverlap: true }
    if (series.markLine?.label) series.markLine.label = { ...series.markLine.label, position: 'insideEndTop' }
  }
  return option
}

export async function chartExportImages(charts, { signal, onProgress = () => {} } = {}) {
  if (!charts.length) return {}
  const { echarts } = await import('./chartEngine.js')
  await document.fonts?.ready
  const images = {}
  for (const [index, item] of charts.entries()) {
    signal?.throwIfAborted()
    onProgress(`正在准备图表 ${index + 1} / ${charts.length}`)
    await yieldToBrowser()
    const host = document.createElement('div')
    host.style.cssText = 'position:fixed;left:-10000px;top:0;width:1600px;height:680px;pointer-events:none'
    document.body.appendChild(host)
    let chart
    try {
      chart = echarts.init(host, null, { renderer: 'canvas' })
      chart.setOption(exportChartOption(item.option, item.show_values), { notMerge: true })
      images[item.id] = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
    } finally {
      chart?.dispose()
      host.remove()
    }
  }
  return images
}

export function saveExportBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
