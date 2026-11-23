import test from 'node:test'
import assert from 'node:assert/strict'
import { exportIdsFromHref } from '../src/utils/xlsxDownload.js'
import { renderMarkdown } from '../src/utils/markdown.js'

test('export path is parsed from a download href', () => {
  assert.deepEqual(
    exportIdsFromHref('/api/v2/runs/run-1/exports/artifact_9'),
    { runId: 'run-1', exportId: 'artifact_9' },
  )
  assert.equal(exportIdsFromHref('https://example.test/other'), null)
})

test('markdown download links keep a relative export href', () => {
  const html = renderMarkdown('[下载完整结果.xlsx](/api/v2/runs/run-1/exports/artifact_1)')
  assert.match(html, /\/api\/v2\/runs\/run-1\/exports\/artifact_1/)
})
