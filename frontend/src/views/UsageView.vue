<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../api/backend.js'
import { formatDate, showToast } from '../store.js'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const loading = ref(true)
const summaryLoading = ref(false)
const events = ref([])
const summary = ref([])
const total = ref(0)
const sumTokens = ref(0)
const trend = ref({ points: [], sum_total_tokens: 0, event_count: 0 })
const chartHost = ref(null)
const tab = ref('events')
const filters = reactive({
  username: '',
  run_id: '',
  since: '',
  until: '',
})
const page = reactive({ limit: 10, offset: 0 })
let chart = null

const MODE_LABEL = { normal: '问数', insight: '洞察' }

function dayBoundaryIso(ymd, endOfDay = false) {
  const text = String(ymd || '').trim()
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return ''
  const stamp = endOfDay ? `${text}T23:59:59.999` : `${text}T00:00:00`
  const date = new Date(stamp)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function openDatePicker(event) {
  const input = event.currentTarget?.parentElement?.querySelector('input[type="date"]')
  if (!input) return
  try {
    if (typeof input.showPicker === 'function') input.showPicker()
    else input.focus()
  } catch {
    input.focus()
  }
}

const filterParams = computed(() => {
  const params = {
    limit: page.limit,
    offset: page.offset,
  }
  if (filters.username.trim()) params.username = filters.username.trim()
  if (filters.run_id.trim()) params.run_id = filters.run_id.trim()
  const since = dayBoundaryIso(filters.since, false)
  const until = dayBoundaryIso(filters.until, true)
  if (since) params.since = since
  if (until) params.until = until
  return params
})

async function reloadEvents() {
  loading.value = true
  try {
    const result = await api.usageEvents(filterParams.value)
    events.value = result.items || []
    total.value = result.total || 0
    sumTokens.value = result.sum_total_tokens || 0
  } catch (error) {
    showToast('消耗记录加载失败：' + error.message)
  } finally {
    loading.value = false
  }
}

async function reloadSummary() {
  summaryLoading.value = true
  try {
    const { limit: _l, offset: _o, run_id: _r, ...rest } = filterParams.value
    summary.value = await api.usageSummary({ ...rest, limit: 100 })
  } catch (error) {
    showToast('汇总加载失败：' + error.message)
  } finally {
    summaryLoading.value = false
  }
}

async function reloadTrend() {
  try {
    const params = {}
    const since = dayBoundaryIso(filters.since, false)
    const until = dayBoundaryIso(filters.until, true)
    if (since) params.since = since
    if (until) params.until = until
    trend.value = await api.usageTrend(params)
  } catch (error) {
    showToast('用量趋势加载失败：' + error.message)
  }
  await nextTick()
  renderChart()
}

function renderChart() {
  if (!chartHost.value) return
  if (!chart) chart = echarts.init(chartHost.value)
  const points = trend.value?.points || []
  chart.setOption({
    grid: { left: 56, right: 16, top: 40, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: points.map(item => String(item.bucket || '').slice(0, 10)),
      axisLabel: { color: '#6a5d64' },
    },
    yAxis: {
      type: 'value',
      name: 'tokens',
      nameGap: 12,
      nameTextStyle: { color: '#6a5d64', padding: [0, 0, 0, 0] },
      axisLabel: { color: '#6a5d64' },
      splitLine: { lineStyle: { color: 'rgba(43, 22, 34, .08)' } },
    },
    series: [{
      type: 'line',
      smooth: true,
      showSymbol: points.length < 24,
      data: points.map(item => item.total_tokens || 0),
      areaStyle: { color: 'rgba(138, 23, 77, .12)' },
      lineStyle: { color: '#8a174d', width: 2 },
      itemStyle: { color: '#8a174d' },
    }],
  }, true)
  chart.resize()
}

async function reload() {
  const jobs = [reloadTrend()]
  if (tab.value === 'summary') jobs.push(reloadSummary())
  else jobs.push(reloadEvents())
  await Promise.all(jobs)
}

function search() {
  page.offset = 0
  void reload()
}

function switchTab(next) {
  tab.value = next
  page.offset = 0
  void reload()
}

function prevPage() {
  page.offset = Math.max(0, page.offset - page.limit)
  void reloadEvents()
}

function nextPage() {
  if (page.offset + page.limit >= total.value) return
  page.offset += page.limit
  void reloadEvents()
}

function formatNum(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function onResize() {
  chart?.resize()
}

watch(chartHost, () => nextTick(renderChart))

const quotas = ref([]), quotaError = ref(''), resetting = ref(false)
async function reloadQuota() { try { quotas.value=await api.quotas(); quotaError.value='' } catch(e) { quotaError.value=e.message } }
async function reset(q) {
  if (!window.confirm('重置 '+q.username+' 的本月额度？用量明细会保留。')) return
  resetting.value=true
  try { await api.resetQuota(q.user_id); await reloadQuota(); window.dispatchEvent(new Event('quota-updated')) }
  catch(e) { quotaError.value=e.message } finally { resetting.value=false }
}
onMounted(() => {
  reloadQuota()
  window.addEventListener('resize', onResize)
  void reload()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="page-shell">
    <section class="quota-admin"><h2>每月 Token 配额</h2><p>北京时间每月 1 日零点刷新。</p>
      <p v-if="quotaError" role="alert">{{quotaError}}</p>
      <table><thead><tr><th>账号</th><th>已用</th><th>额度</th><th>剩余</th><th></th></tr></thead><tbody>
      <tr v-for="q in quotas" :key="q.user_id"><td>{{q.display_name}} · {{q.username}}</td><td>{{q.used.toLocaleString()}}</td><td>{{q.limit.toLocaleString()}}</td><td>{{q.remaining.toLocaleString()}}</td><td><button :disabled="!q.exhausted || resetting" @click="reset(q)">重置额度</button></td></tr>
      </tbody></table></section>
    <header class="page-head">
      <div>
        <h1>Token 消耗</h1>
        <p>查看账号及每次调用的实际消耗。</p>
      </div>
      <div class="tabs">
        <button type="button" :class="{ on: tab === 'events' }" @click="switchTab('events')">明细</button>
        <button type="button" :class="{ on: tab === 'summary' }" @click="switchTab('summary')">按用户汇总</button>
      </div>
    </header>

    <section class="panel filters">
      <label class="f-user"><span>用户名</span><input v-model="filters.username" placeholder="精确匹配" @keyup.enter="search" /></label>
      <label class="f-run"><span>Run ID</span><input v-model="filters.run_id" placeholder="可选" @keyup.enter="search" /></label>
      <label class="f-date">
        <span>起始日期</span>
        <span class="date-wrap">
          <button type="button" class="date-face" @click="openDatePicker">
            <span v-if="filters.since" class="date-value">{{ filters.since }}</span>
            <span v-else class="date-ph">选择日期</span>
          </button>
          <input v-model="filters.since" type="date" class="date-ghost" tabindex="-1" aria-hidden="true" />
        </span>
      </label>
      <label class="f-date">
        <span>截止日期</span>
        <span class="date-wrap">
          <button type="button" class="date-face" @click="openDatePicker">
            <span v-if="filters.until" class="date-value">{{ filters.until }}</span>
            <span v-else class="date-ph">选择日期</span>
          </button>
          <input v-model="filters.until" type="date" class="date-ghost" tabindex="-1" aria-hidden="true" />
        </span>
      </label>
      <button class="btn-p filter-go" type="button" @click="search">查询</button>
    </section>

    <section class="panel chart-card">
      <div class="chart-head">
        <div>
          <h2>平台 Token 合计</h2>
          <p>按日汇总全部用户的合计 tokens，共 {{ formatNum(trend.sum_total_tokens) }}</p>
        </div>
      </div>
      <div ref="chartHost" class="chart-host"></div>
    </section>

    <section v-if="tab === 'events'" class="panel table-card">
      <div class="meta-row">
        <span>共 {{ formatNum(total) }} 条问题 · 合计 {{ formatNum(sumTokens) }} tokens</span>
        <div class="pager">
          <button type="button" class="btn-g" :disabled="page.offset <= 0" @click="prevPage">上一页</button>
          <button type="button" class="btn-g" :disabled="page.offset + page.limit >= total" @click="nextPage">下一页</button>
        </div>
      </div>
      <div v-if="loading" class="loading-state">加载中…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>用户</th>
              <th>模式</th>
              <th>问题</th>
              <th>模型</th>
              <th class="num">合计</th>
              <th>Run</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!events.length">
              <td colspan="7" class="empty">暂无消耗记录。用户提问后会按问题汇总展示。</td>
            </tr>
            <tr v-for="row in events" :key="row.id">
              <td>{{ formatDate(row.created_at) }}</td>
              <td>
                <b>{{ row.display_name || row.username }}</b>
                <small>{{ row.username }}</small>
              </td>
              <td>{{ MODE_LABEL[row.mode] || row.mode }}</td>
              <td class="question" :title="row.question || ''">{{ row.question || '—' }}</td>
              <td>{{ row.model_id || '—' }}</td>
              <td class="num">
                <b>{{ formatNum(row.total_tokens) }}</b>
                <small v-if="row.event_count > 1">{{ row.event_count }} 次调用</small>
              </td>
              <td><code class="run">{{ row.run_id || '—' }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-else class="panel table-card">
      <div v-if="summaryLoading" class="loading-state">加载中…</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th class="num">事件数</th>
              <th class="num">合计 tokens</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!summary.length">
              <td colspan="3" class="empty">暂无汇总数据</td>
            </tr>
            <tr v-for="row in summary" :key="row.user_id">
              <td>
                <b>{{ row.display_name || row.username }}</b>
                <small>{{ row.username }} · {{ row.user_id }}</small>
              </td>
              <td class="num">{{ formatNum(row.event_count) }}</td>
              <td class="num"><b>{{ formatNum(row.total_tokens) }}</b></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.quota-admin{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:20px}.quota-admin h2{margin:0;font-size:18px}.quota-admin p{font-size:13px;color:var(--ink-2)}.quota-admin table{width:100%;text-align:left;font-size:13px}.quota-admin th,.quota-admin td{padding:8px}.quota-admin button{cursor:pointer}
.page-head {
  align-items: end;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 14px;
}
.page-head h1 { font-size: 20px; margin: 0 0 4px; }
.page-head p { color: var(--ink-3); font-size: 13px; margin: 0; }
.tabs { display: flex; gap: 6px; }
.tabs button {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  font: 600 12px var(--body-font);
  padding: 6px 12px;
}
.tabs button.on {
  border-color: var(--accent);
  color: var(--accent-dark);
}
.filters {
  align-items: end;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 14px;
  margin-bottom: 12px;
  padding: 14px 16px;
}
.chart-card, .table-card { margin-bottom: 12px; padding: 16px 18px 18px; }
.chart-head h2 { font-size: 15px; margin: 0 0 4px; }
.chart-head p { color: var(--ink-3); font-size: 12px; margin: 0 0 8px; }
.chart-host { height: 240px; width: 100%; }
.filters label { display: grid; gap: 4px; font-size: 12px; color: var(--ink-3); }
.filters .f-user { width: 118px; }
.filters .f-run { width: 150px; }
.filters .f-date { width: 142px; }
.filters input, .filters select {
  border: 1px solid var(--line);
  border-radius: 8px;
  font: 13px var(--body-font);
  min-height: 34px;
  padding: 6px 8px;
  width: 100%;
}
.date-wrap {
  display: block;
  position: relative;
}
.date-face {
  align-items: center;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink);
  cursor: pointer;
  display: flex;
  font: 13px var(--body-font);
  min-height: 34px;
  padding: 6px 8px;
  text-align: left;
  width: 100%;
}
.date-face:hover { border-color: var(--accent); }
.date-ph { color: var(--ink-3); }
.date-value { color: var(--ink); font-variant-numeric: tabular-nums; }
.date-ghost {
  height: 0;
  left: 0;
  opacity: 0;
  pointer-events: none;
  position: absolute;
  top: 0;
  width: 0;
}
.filter-go {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 16px;
}
.meta-row {
  align-items: center;
  color: var(--ink-2);
  display: flex;
  font-size: 13px;
  justify-content: space-between;
  margin: 0 0 14px;
  padding: 2px 2px 0;
}
.pager { display: flex; gap: 8px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; min-width: 860px; width: 100%; }
th, td {
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
th { color: var(--ink-3); font-weight: 700; }
td.num, th.num { font-feature-settings: "tnum"; text-align: right; }
td.question {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
td b { display: block; }
td small { color: var(--ink-3); display: block; font-size: 11px; margin-top: 2px; }
code { font: 11px/1.4 var(--mono-font); }
code.run { color: var(--ink-3); }
.empty { color: var(--ink-3); text-align: center !important; }
</style>
