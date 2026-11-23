<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, showToast } from '../store.js'

const loading = ref(true)
const items = ref([])
const total = ref(0)
const upCount = ref(0)
const downCount = ref(0)
const filters = reactive({
  username: '',
  run_id: '',
  rating: '',
  since: '',
  until: '',
})
const page = reactive({ limit: 20, offset: 0 })

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
  if (filters.rating) params.rating = filters.rating
  const since = dayBoundaryIso(filters.since, false)
  const until = dayBoundaryIso(filters.until, true)
  if (since) params.since = since
  if (until) params.until = until
  return params
})

async function reload() {
  loading.value = true
  try {
    const result = await api.adminFeedback(filterParams.value)
    items.value = result.items || []
    total.value = result.total || 0
    upCount.value = result.up_count || 0
    downCount.value = result.down_count || 0
  } catch (error) {
    showToast('运维看板加载失败：' + error.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.offset = 0
  void reload()
}

function prevPage() {
  page.offset = Math.max(0, page.offset - page.limit)
  void reload()
}

function nextPage() {
  if (page.offset + page.limit >= total.value) return
  page.offset += page.limit
  void reload()
}

function formatNum(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function ratingLabel(rating) {
  if (rating === 'up') return '点赞'
  if (rating === 'down') return '点踩'
  return rating || '—'
}

onMounted(() => {
  void reload()
})
</script>

<template>
  <div class="page-shell">
    <header class="page-head">
      <div>
        <h1>运维看板</h1>
        <p>汇总用户对每次回答的点赞 / 点踩，便于跟踪问题质量与体验。</p>
      </div>
    </header>

    <section class="stats">
      <article class="stat">
        <span>反馈总数</span>
        <b>{{ formatNum(total) }}</b>
      </article>
      <article class="stat up">
        <span>点赞</span>
        <b>{{ formatNum(upCount) }}</b>
      </article>
      <article class="stat down">
        <span>点踩</span>
        <b>{{ formatNum(downCount) }}</b>
      </article>
    </section>

    <section class="panel filters">
      <label class="f-user"><span>用户名</span><input v-model="filters.username" placeholder="精确匹配" @keyup.enter="search" /></label>
      <label class="f-run"><span>Run ID</span><input v-model="filters.run_id" placeholder="可选" @keyup.enter="search" /></label>
      <label class="f-rating">
        <span>评价</span>
        <select v-model="filters.rating">
          <option value="">全部</option>
          <option value="up">点赞</option>
          <option value="down">点踩</option>
        </select>
      </label>
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

    <section class="panel table-card">
      <div class="meta-row">
        <span>共 {{ formatNum(total) }} 条反馈</span>
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
              <th>评价</th>
              <th>问题</th>
              <th>Run</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!items.length">
              <td colspan="5" class="empty">暂无反馈。用户在回答结束后点赞 / 点踩后会出现在这里。</td>
            </tr>
            <tr v-for="row in items" :key="row.id">
              <td>{{ formatDate(row.created_at) }}</td>
              <td>
                <b>{{ row.display_name || row.username }}</b>
                <small>{{ row.username }}</small>
              </td>
              <td>
                <span class="pill" :class="row.rating">{{ ratingLabel(row.rating) }}</span>
              </td>
              <td class="question" :title="row.question || ''">{{ row.question || '—' }}</td>
              <td><code class="run">{{ row.run_id || '—' }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 14px; }
.page-head h1 { font-size: 20px; margin: 0 0 4px; }
.page-head p { color: var(--ink-3); font-size: 13px; margin: 0; }
.stats {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  margin-bottom: 12px;
}
.stat {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  padding: 14px 16px;
}
.stat span { color: var(--ink-3); display: block; font-size: 12px; }
.stat b { display: block; font-size: 22px; font-weight: 700; margin-top: 4px; }
.stat.up b { color: var(--success); }
.stat.down b { color: var(--danger); }
.filters {
  align-items: end;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 14px;
  margin-bottom: 12px;
  padding: 14px 16px;
}
.filters label { display: grid; gap: 4px; font-size: 12px; color: var(--ink-3); }
.filters .f-user { width: 118px; }
.filters .f-run { width: 150px; }
.filters .f-rating { width: 96px; }
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
.table-card { margin-bottom: 12px; padding: 16px 18px 18px; }
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
table { border-collapse: collapse; min-width: 780px; width: 100%; }
th, td {
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
th { color: var(--ink-3); font-weight: 700; }
td.question {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
td b { display: block; }
td small { color: var(--ink-3); display: block; font-size: 11px; margin-top: 2px; }
code.run { color: var(--ink-3); font: 11px/1.4 var(--mono-font); }
.pill {
  border-radius: 999px;
  display: inline-block;
  font: 650 11px var(--body-font);
  padding: 3px 8px;
}
.pill.up { background: color-mix(in srgb, var(--success) 14%, #fff); color: var(--success); }
.pill.down { background: #f8ece9; color: var(--danger); }
.empty { color: var(--ink-3); text-align: center !important; }
</style>
