import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createSampleReport } from './sample-data.mjs'
import { buildReportHtml } from '../src/reports/template.js'
import { reportView } from '../src/reports/model.js'

const output = new URL('../../../outputs/AI4BI报表/', import.meta.url)
await mkdir(output, { recursive: true })
const report = createSampleReport()
await writeFile(new URL('report-sample-data.json', output), JSON.stringify(report))
await writeFile(new URL('DDI商业表现分析.html', output), buildReportHtml(report))
const other = createSampleReport('insight')
other.dimension = 'channel'
other.title = '终端渠道结构与增长归因'
await writeFile(new URL('商业洞察报告.html', output), buildReportHtml(other))
const view = reportView(report)
await writeFile(new URL('data-validation.json', output), JSON.stringify({
  rows: report.rows.length, period: view.selected, period_rows: view.sourceRows.length,
  totals: view.totals, regions: view.groups.map(({ rows, ...group }) => group),
}, null, 2))
console.log(fileURLToPath(output))
