<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { echarts } from '../../utils/chartEngine.js'
import { chartDataFor, kpiDisplay } from '../../utils/analysisCharts.js'
import ResultTable from './ResultTable.vue'
import ExportMenu from '../ExportMenu.vue'

const props = defineProps({
  charts: { type: Object, required: true },
  allowPin: { type: Boolean, default: false },
  hideTitle: { type: Boolean, default: false },
  exportSource: { type: Object, default: null },
})
const emit = defineEmits(['pin', 'pin-analysis', 'pin-table', 'view-change'])

const host = ref(null)
const selectedType = ref('')
const renderError = ref('')
const showValues = ref(false)
const detailMode = ref(false)
let chart = null
let resizeObserver = null
let renderToken = 0
let quietUntil = 0
let lineRaf = 0

const items = computed(() => (Array.isArray(props.charts?.charts) ? props.charts.charts : []))
const active = computed(() => items.value.find(item => item.type === selectedType.value) || items.value[0] || null)
const analysis = computed(() => props.charts?.version === 2)
const kpis = computed(() => (props.charts.kpis || []).map(metric => ({ ...metric, display: kpiDisplay(metric) })))
const tabs = computed(() => analysis.value ? items.value.filter(item => ['combo', 'line', 'horizontal_bar'].includes(item.type)) : items.value)
const tableData = computed(() => detailMode.value && props.charts.details ? props.charts.details : chartDataFor(props.charts, active.value))
const exportView = computed(() => ({ chart_type: active.value?.type, show_values: showValues.value }))
const exportSource = computed(() => props.exportSource && (props.exportSource.kind === 'board'
  ? props.exportSource : { ...props.exportSource, chart_type: active.value?.type }))
const tableExportSource = computed(() => exportSource.value && (exportSource.value.kind === 'board'
  ? exportSource.value : { ...exportSource.value, kind: 'chart_table', table_view: detailMode.value ? 'details' : 'chart' }))
watch(exportView, value => emit('view-change', value))
function ensureSelected() {
  if (!items.value.length) {
    selectedType.value = ''
    return
  }
  const preferred = props.charts?.default_type || items.value[0]?.type
  if (!items.value.some(item => item.type === selectedType.value)) {
    selectedType.value = preferred
  }
}

function cssToken(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function cloneOption(raw) {
  const plain = toRaw(raw)
  try {
    return JSON.parse(JSON.stringify(plain))
  } catch {
    return plain && typeof plain === 'object' ? { ...plain } : plain
  }
}

function polishOption(raw) {
  if (!raw || typeof raw !== 'object') return raw
  const ink = cssToken('--ink', '#0F172A')
  const ink2 = cssToken('--ink-2', '#64748B')
  const option = JSON.parse(JSON.stringify(cloneOption(raw), (_key, value) => {
    const replacements = { '#193d60': '#c5203f', '#112b46': '#881222', '#b33a52': '#3fb9c2' }
    return typeof value === 'string' ? (replacements[value.toLowerCase()] || value) : value
  }))
  if (!option || typeof option !== 'object') return raw

  option.animation = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  option.animationThreshold = 8000
  option.animationDuration = 900
  option.animationEasing = 'cubicOut'
  option.animationDurationUpdate = 900
  option.animationEasingUpdate = 'cubicOut'

  if (option.title && typeof option.title === 'object') {
    option.title.textStyle = {
      fontFamily: "Inter, system-ui, -apple-system, 'PingFang SC', sans-serif",
      ...(option.title.textStyle || {}),
      color: option.title.textStyle?.color || ink,
    }
  }

  const seriesList = Array.isArray(option.series) ? option.series : []
  for (const series of seriesList) {
    if (!series || typeof series !== 'object') continue
    delete series._stagger_ms

    if (series.type === 'bar') {
      const style = series.itemStyle || {}
      series.itemStyle = {
        ...style,
        borderRadius: style.borderRadius || [8, 8, 2, 2],
      }
      series.animationDuration = 900
      series.animationEasing = 'cubicOut'
      series.animationDelay = (idx) => idx * 80
      series.animationDelayUpdate = (idx) => idx * 80
      series.emphasis = { focus: 'self', ...(series.emphasis || {}) }
      series.blur = series.blur || { itemStyle: { opacity: 0.25 } }
    } else if (series.type === 'line') {
      series.smooth = series.smooth ?? true
      series.symbolSize = series.symbolSize ?? 6
      series.showSymbol = true
      series.animationDuration = 900
      series.animationEasing = 'cubicOut'
      series.emphasis = { focus: 'series', ...(series.emphasis || {}) }
      series.blur = series.blur || {
        lineStyle: { opacity: 0.2 },
        itemStyle: { opacity: 0.2 },
      }
    } else if (series.type === 'pie') {
      series.animationType = 'expansion'
      series.animationDuration = 900
      series.animationEasing = 'cubicOut'
      series.animationDelay = (idx) => idx * 70
      series.animationDelayUpdate = (idx) => idx * 70
      series.label = { ...(series.label || {}), show: true }
      series.labelLine = { show: true, ...(series.labelLine || {}) }
    }
  }

  if (!Array.isArray(option.color) || !option.color.length) {
    option.color = ['#c5203f', '#203662', '#3fb9c2', '#94a3b8', '#dca965']
  }

  if (option.legend && typeof option.legend === 'object') {
    option.legend.textStyle = {
      color: ink2,
      fontSize: 11,
      fontFamily: "Inter, system-ui, 'PingFang SC', sans-serif",
      ...(option.legend.textStyle || {}),
    }
  }

  return option
}

function zeroPoint(point, seriesType) {
  if (seriesType === 'pie') {
    if (point && typeof point === 'object') return { ...point, value: 0 }
    return { value: 0 }
  }
  if (point && typeof point === 'object' && !Array.isArray(point)) {
    return { ...point, value: 0 }
  }
  if (Array.isArray(point)) {
    // scatter [x, y] → keep x, zero y
    if (point.length >= 2) return [point[0], 0]
    return point
  }
  return 0
}

function withZeroedSeries(option) {
  const next = cloneOption(option)
  next.animation = false
  next.animationDuration = 0
  next.animationDurationUpdate = 0
  const list = Array.isArray(next.series) ? next.series : []
  for (const series of list) {
    if (!series || !Array.isArray(series.data)) continue
    series.animation = false
    series.animationDuration = 0
    series.data = series.data.map((point) => zeroPoint(point, series.type))
  }
  return next
}

function clearLineRaf() {
  if (lineRaf) {
    cancelAnimationFrame(lineRaf)
    lineRaf = 0
  }
}

function pointValue(point) {
  if (point == null) return null
  if (typeof point === 'number') return point
  if (typeof point === 'object' && !Array.isArray(point) && point.value != null) {
    return Number(point.value)
  }
  if (Array.isArray(point) && point.length >= 2) return Number(point[1])
  const n = Number(point)
  return Number.isFinite(n) ? n : null
}

/**
 * Category axes only allow integer slots — interpolating Y still jumps node-to-node.
 * During the stroke we temporarily use a value X axis so the tip can glide continuously.
 */
function playLineDraw(token, option) {
  const series = option.series?.[0]
  if (!series || series.type !== 'line' || !Array.isArray(series.data) || !series.data.length) {
    chart.setOption(option, { notMerge: true, lazyUpdate: false })
    return
  }
  const values = series.data.map(pointValue)
  const n = values.length
  const categories = Array.isArray(option.xAxis?.data) ? option.xAxis.data.map(String) : values.map((_, i) => String(i + 1))
  if (n === 1 || values.every((v) => v == null)) {
    chart.setOption(option, { notMerge: true, lazyUpdate: false })
    return
  }

  const anim = cloneOption(option)
  anim.animation = false
  anim.animationDuration = 0
  anim.animationDurationUpdate = 0
  anim.xAxis = {
    type: 'value',
    min: 0,
    max: Math.max(n - 1, 1),
    interval: 1,
    boundaryGap: false,
    axisLabel: {
      ...(option.xAxis?.axisLabel || {}),
      hideOverlap: true,
      formatter: (x) => {
        const idx = Math.round(Number(x))
        if (Math.abs(Number(x) - idx) > 0.02) return ''
        return categories[idx] ?? ''
      },
    },
    axisLine: option.xAxis?.axisLine || { show: false },
    axisTick: option.xAxis?.axisTick || { show: false },
    splitLine: { show: false },
  }
  // Straight segments while drawing — smooth bezier would reshape every frame and look jumpy.
  // Keep symbols off for the whole stroke; toggling them near nodes causes flicker.
  anim.series[0].smooth = false
  anim.series[0].showSymbol = false
  anim.series[0].symbol = 'none'
  anim.series[0].clip = true
  anim.series[0].data = [[0, values[0]]]
  chart.setOption(anim, { notMerge: true, lazyUpdate: false })

  // ~240ms per segment — a touch faster than before, still smooth.
  const duration = Math.max(1500, Math.min(3000, 240 * (n - 1)))
  const started = performance.now()
  clearLineRaf()

  const tick = (now) => {
    if (token !== renderToken || !chart) {
      clearLineRaf()
      return
    }
    const t = Math.min(1, (now - started) / duration)
    // Slight ease-in-out keeps motion even across the whole path.
    const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
    const pos = eased * (n - 1)
    const i = Math.min(n - 2, Math.floor(pos))
    const frac = Math.min(1, pos - i)
    const a = values[i]
    const b = values[i + 1]
    const tipY = a != null && b != null ? a + (b - a) * frac : (b ?? a)

    const drawn = []
    for (let j = 0; j <= i; j += 1) {
      if (values[j] != null) drawn.push([j, values[j]])
    }
    if (tipY != null) drawn.push([i + frac, tipY])

    chart.setOption(
      {
        animation: false,
        series: [
          {
            data: drawn,
            smooth: false,
            showSymbol: false,
            symbol: 'none',
          },
        ],
      },
      { notMerge: false, lazyUpdate: false },
    )

    if (t < 1) {
      lineRaf = requestAnimationFrame(tick)
    } else {
      lineRaf = 0
      // Restore category axis + original smooth styling without a second entrance anim.
      const finalOpt = cloneOption(option)
      finalOpt.animation = false
      finalOpt.animationDuration = 0
      chart.setOption(finalOpt, { notMerge: true, lazyUpdate: false })
    }
  }
  lineRaf = requestAnimationFrame(tick)
}

function playBarOrPieRise(token, option) {
  // Phase 1: layout at zero height / zero slice — no animation.
  chart.setOption(withZeroedSeries(option), { notMerge: true, lazyUpdate: false })
  // Phase 2: rise to real values — ECharts update animation = grow from bottom.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (token !== renderToken || !chart) return
      const live = cloneOption(option)
      live.animation = true
      live.animationDuration = 900
      live.animationDurationUpdate = 900
      live.animationEasing = 'cubicOut'
      live.animationEasingUpdate = 'cubicOut'
      for (const series of live.series || []) {
        if (!series) continue
        if (series.type === 'bar') {
          series.animationDuration = 900
          series.animationDurationUpdate = 900
          series.animationEasing = 'cubicOut'
          series.animationDelay = (idx) => idx * 80
          series.animationDelayUpdate = (idx) => idx * 80
        }
        if (series.type === 'pie') {
          series.animationType = 'expansion'
          series.animationDuration = 900
          series.animationDurationUpdate = 900
          series.animationDelay = (idx) => idx * 70
          series.animationDelayUpdate = (idx) => idx * 70
        }
      }
      chart.setOption(live, { notMerge: true, lazyUpdate: false })
    })
  })
}

function render() {
  if (!host.value || !active.value?.option) return
  const token = ++renderToken
  clearLineRaf()
  quietUntil = analysis.value ? 0 : Date.now() + Math.max(2000, (active.value?.option?.series?.[0]?.data?.length || 8) * 260)
  try {
    // Fresh instance so entrance animation is never skipped as an "update".
    if (chart) {
      try {
        chart.dispose()
      } catch {
        /* ignore */
      }
      chart = null
    }
    chart = echarts.init(host.value, null, { renderer: 'canvas' })
    const option = polishOption(active.value.option)
    if (analysis.value) {
      for (const series of option.series || []) {
        if (['bar', 'line', 'scatter', 'pie', 'radar'].includes(series.type)) {
          series.label = { ...(series.label || {}), show: showValues.value }
          series.labelLayout = { hideOverlap: true }
        }
      }
      for (const axis of [option.xAxis, option.yAxis].flat().filter(Boolean)) {
        if (axis.type === 'value' && !axis.axisLabel?.formatter) {
          axis.axisLabel = { ...(axis.axisLabel || {}), formatter: value => Math.abs(value) >= 1e8 ? `${Number((value / 1e8).toFixed(1))}亿` : Math.abs(value) >= 1e4 ? `${Number((value / 1e4).toFixed(1))}万` : Number(value).toLocaleString('zh-CN') }
        }
      }
      if (host.value.clientWidth < 600) {
        if (option.title) {
          option.title.textStyle = { ...option.title.textStyle, fontSize: 13, overflow: 'truncate', width: host.value.clientWidth - 28 }
        }
        const yAxes = Array.isArray(option.yAxis) ? option.yAxis : [option.yAxis]
        yAxes.forEach((axis, index) => { if (axis && index > 1) axis.offset = (index - 1) * 48 })
        if (option.grid && yAxes.length > 2) option.grid.right = 120
      }
    }
    if (props.hideTitle) {
      option.title = { show: false }
      for (const key of ['xAxis', 'yAxis']) {
        for (const axis of Array.isArray(option[key]) ? option[key] : [option[key]]) {
          if (axis?.type === 'value' && !axis.axisLabel?.formatter) {
            axis.axisLabel = { ...(axis.axisLabel || {}), formatter: value => Math.abs(value) >= 1e8 ? `${Number((value / 1e8).toFixed(1))}亿` : Math.abs(value) >= 1e4 ? `${Number((value / 1e4).toFixed(1))}万` : Number(value).toLocaleString('zh-CN') }
          }
        }
      }
    }
    const mainType = option.series?.[0]?.type

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      option.animation = false
      for (const series of option.series || []) series.animation = false
      chart.setOption(option, { notMerge: true, lazyUpdate: false })
    } else if (analysis.value) {
      chart.setOption(option, { notMerge: true, lazyUpdate: false })
    } else if (mainType === 'line' && option.series.length === 1) {
      playLineDraw(token, option)
    } else if (mainType === 'bar' || mainType === 'pie' || mainType === 'stacked_bar') {
      playBarOrPieRise(token, option)
    } else {
      chart.setOption(option, { notMerge: true, lazyUpdate: false })
    }
    renderError.value = ''
  } catch (error) {
    renderError.value = '图表渲染失败，请切换类型重试'
    console.warn('[AnswerCharts] render failed', error)
  }
}

function pick(type) {
  if (selectedType.value === type) return
  selectedType.value = type
}

function onResize() {
  if (Date.now() < quietUntil) return
  try {
    chart?.resize()
  } catch {
    /* ignore */
  }
}

watch(
  () => props.charts,
  async () => {
    ensureSelected()
    await nextTick()
    render()
  },
  { deep: true },
)

watch(selectedType, async () => {
  await nextTick()
  render()
})
watch(showValues, () => render())

onMounted(async () => {
  ensureSelected()
  await nextTick()
  render()
  window.addEventListener('resize', onResize)
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    resizeObserver = new ResizeObserver(() => onResize())
    resizeObserver.observe(host.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  clearLineRaf()
  renderToken += 1
  try {
    chart?.dispose()
  } catch {
    /* ignore */
  }
  chart = null
})
</script>

<template>
  <section v-if="items.length" class="answer-charts" :class="{ 'analysis-card': analysis }" aria-label="数据图表">
    <header v-if="analysis && !hideTitle" class="analysis-heading">
      <span class="analysis-eyebrow">医药经营分析</span>
      <h3>{{ charts.title || '经营表现' }}</h3>
      <p v-if="charts.scope">{{ charts.scope }}</p>
    </header>
    <div v-if="kpis.length" class="analysis-kpis" aria-label="关键指标">
      <article v-for="metric in kpis" :key="metric.label" class="analysis-kpi">
        <span>{{ metric.label }}</span>
        <strong :class="{ negative: Number(metric.value) < 0 }" :title="metric.display.exact">{{ metric.display.value }}<small>{{ metric.display.unit }}</small></strong>
        <p>{{ metric.note || '当前查询范围' }}</p>
      </article>
    </div>
    <div class="chart-switch" :role="analysis ? 'toolbar' : 'tablist'" aria-label="图表操作">
      <label v-if="analysis" class="chart-type-select"><span>图表</span><select :value="active?.type" aria-label="图表类型" @change="pick($event.target.value)"><option v-for="item in items" :key="item.type" :value="item.type">{{ item.label }}</option></select></label>
      <button
        v-for="item in tabs"
        :key="item.type"
        type="button"
        :role="analysis ? 'button' : 'tab'"
        class="chart-tab"
        :class="{ on: item.type === (active?.type || '') }"
        :aria-selected="analysis ? undefined : item.type === (active?.type || '')"
        :aria-pressed="analysis ? item.type === (active?.type || '') : undefined"
        @click="pick(item.type)"
      >
        {{ item.label || item.type }}
      </button>
      <label v-if="analysis" class="chart-label-toggle"><input v-model="showValues" type="checkbox" />显示数值</label>
      <ExportMenu v-if="exportSource" :source="exportSource" :view="exportView" />
      <button v-if="allowPin" type="button" class="chart-pin" @click="emit('pin-analysis', active?.type)">＋ 整块分析加入看板</button>
      <button v-if="allowPin" type="button" class="chart-pin" @click="emit('pin', active?.type)">＋ 当前图表加入看板</button>
    </div>
    <div class="chart-stage">
      <div ref="host" class="chart-host" role="img" :aria-label="active?.label || '图表'"></div>
      <p v-if="renderError" class="chart-error">{{ renderError }}</p>
    </div>
    <p v-if="active?.note" class="chart-scope-note">{{ active.note }}</p>
    <p v-for="warning in charts.warnings || []" :key="warning" class="chart-warning">{{ warning }}</p>
    <ResultTable
      :data="tableData"
      :title="detailMode ? '查询明细' : '图表数据'"
      :filename="`${charts.title || active?.label || '业务分析'}_${detailMode ? '查询明细' : '图表数据'}`"
      :allow-pin="allowPin"
      :export-source="tableExportSource"
      :export-view="{ ...exportView, table_only: true, table_view: detailMode ? 'details' : 'chart' }"
      @pin="emit('pin-table', { type: active?.type, view: detailMode ? 'details' : 'chart' })"
    >
      <template #actions>
        <button v-if="charts.details" type="button" @click="detailMode = !detailMode">{{ detailMode ? '返回图表数据' : '查看查询明细' }}</button>
      </template>
    </ResultTable>
  </section>
</template>

<style scoped>
.chart-pin{margin-left:auto;align-self:center;border:1px solid #ead4de;border-radius:8px;background:#fff6f9;color:#af3d60;font-size:10px;padding:7px 10px;cursor:pointer;white-space:nowrap}
.answer-charts {
  margin-top: 18px;
  padding-top: 4px;
}
.chart-switch {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(var(--accent-rgb, 31, 107, 82), 0.12);
}
.chart-tab {
  position: relative;
  background: transparent;
  border: 0;
  border-radius: 8px 8px 0 0;
  color: var(--ink-3, #94a3b8);
  cursor: pointer;
  font: 600 12.5px/1 var(--body-font);
  letter-spacing: 0.01em;
  padding: 10px 14px 12px;
  transition: color 0.2s ease, background 0.2s ease;
}
.chart-tab:hover {
  color: var(--ink-2, #64748b);
  background: rgba(var(--accent-rgb, 31, 107, 82), 0.05);
}
.chart-tab.on {
  color: var(--accent, #22c55e);
  background: transparent;
}
.chart-tab.on::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--accent, #22c55e), #38bdf8);
}
.chart-stage {
  position: relative;
  border-radius: 16px;
  background:
    radial-gradient(120% 80% at 100% 0%, rgba(56, 189, 248, 0.08), transparent 55%),
    radial-gradient(90% 70% at 0% 100%, rgba(34, 197, 94, 0.07), transparent 50%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.72), rgba(248, 250, 252, 0.92));
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.14);
  overflow: hidden;
}
.chart-host {
  height: 380px;
  width: 100%;
}
.chart-error {
  margin: 0;
  padding: 0 16px 14px;
  color: var(--danger, #a63838);
  font-size: 12px;
}
@media (max-width: 640px) {
  .chart-host {
    height: 280px;
  }
  .chart-tab {
    padding: 9px 10px 11px;
  }
}
</style>

<style scoped src="../../styles/analysis-charts.css"></style>
