/** Usage: node frontend/scripts/export-accepted-reports.mjs RECORDS_DIR OUTPUT_DIR */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { buildReportHtml } from '../src/reports/template.js'

const records = process.argv[2]
const output = process.argv[3]
if (!records || !output) throw new Error('请指定验收记录目录和 HTML 输出目录')
await mkdir(output, { recursive: true })
for (const [source, filename] of [
  ['insight-ddi-complete', 'DDI商业表现分析.html'],
  ['ddi-findings-reviewed', 'DDI商业表现分析_修订.html'],
  ['insight-gap-refined', '商业洞察报告.html'],
  ['insight-skill-reuse-reviewed', '区域缺口归因_202608.html'],
]) {
  const report = JSON.parse(await readFile(resolve(records, source + '-report.json'), 'utf8'))
  await writeFile(resolve(output, filename), buildReportHtml(report))
  console.log(`${filename} · v${report.revision} · ${report.rows.length} 条源记录`)
}
