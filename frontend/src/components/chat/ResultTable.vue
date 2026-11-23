<script setup>
import { computed, ref, watch } from 'vue'
import { analysisCsv, formatChartCell, sortChartRows } from '../../utils/analysisCharts.js'
import ExportMenu from '../ExportMenu.vue'

const props = defineProps({
  data: { type: Object, required: true },
  title: { type: String, default: '数据表' },
  filename: { type: String, default: '' },
  allowPin: { type: Boolean, default: false },
  exportSource: { type: Object, default: null },
  exportView: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['pin'])
const page = ref(1)
const sortIndex = ref(-1)
const sortDirection = ref(1)
const pageSize = 10
const columns = computed(() => props.data.columns || [])
const sortedRows = computed(() => sortChartRows(props.data.rows || [], sortIndex.value, sortDirection.value))
const pageCount = computed(() => Math.max(1, Math.ceil(sortedRows.value.length / pageSize)))
const pageRows = computed(() => sortedRows.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const note = computed(() => {
  if (props.data.query_truncated) return '源查询已截断，此表仅包含已返回数据。'
  if (props.data.preview_truncated) return `表格保留前 ${props.data.rows.length} 行，更多结果可通过问答导出。`
  return '数据与当前统计范围一致。'
})

function sortData(index) {
  sortDirection.value = sortIndex.value === index ? -sortDirection.value : 1
  sortIndex.value = index
  page.value = 1
}

function downloadData() {
  const blob = new Blob([analysisCsv(props.data)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${String(props.filename || props.title).replace(/[\\/:*?"<>|]/g, ' ')}.csv`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

watch(() => props.data, () => { page.value = 1; sortIndex.value = -1 })
</script>

<template>
  <section class="chart-data" :aria-label="title">
    <header class="chart-data-head">
      <div>
        <h4>{{ title }}</h4>
        <span>{{ data.row_count ?? data.rows?.length ?? 0 }} 行 · {{ columns.length }} 列</span>
      </div>
      <slot name="actions"></slot>
      <ExportMenu v-if="exportSource" :source="exportSource" :view="exportView" />
      <button type="button" @click="downloadData">导出 CSV</button>
      <button v-if="allowPin" type="button" class="table-pin" @click="emit('pin')">＋ 表格加入看板</button>
    </header>
    <div class="chart-data-scroll" tabindex="0" aria-label="可横向滚动的数据表">
      <table>
        <thead>
          <tr>
            <th v-for="(column, index) in columns" :key="index">
              <button type="button" :aria-label="`按${column}排序`" @click="sortData(index)">
                {{ column }}<span v-if="sortIndex === index">{{ sortDirection === 1 ? ' ↑' : ' ↓' }}</span>
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in pageRows" :key="index">
            <td v-for="(column, ci) in columns" :key="ci" :class="{ numeric: typeof row[ci] === 'number' }">
              {{ formatChartCell(row[ci], column, data) }}
            </td>
          </tr>
          <tr v-if="!pageRows.length"><td :colspan="Math.max(1, columns.length)">当前结果没有数据</td></tr>
        </tbody>
      </table>
    </div>
    <footer class="chart-data-footer">
      <p>{{ note }}</p>
      <div>
        <button type="button" aria-label="上一页数据" :disabled="page <= 1" @click="page--">‹</button>
        <span>{{ page }} / {{ pageCount }}</span>
        <button type="button" aria-label="下一页数据" :disabled="page >= pageCount" @click="page++">›</button>
      </div>
    </footer>
  </section>
</template>

<style scoped src="../../styles/result-table.css"></style>
