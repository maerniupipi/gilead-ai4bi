import { api } from '../api/backend.js'

const EXPORT_PATH = /\/api\/v2\/runs\/([^/]+)\/exports\/([^/?#]+)/

export function exportIdsFromHref(href) {
  const match = String(href || '').match(EXPORT_PATH)
  if (!match) return null
  return {
    runId: decodeURIComponent(match[1]),
    exportId: decodeURIComponent(match[2]),
  }
}

export async function downloadRunExport(runId, exportId, filename) {
  const result = await api.downloadRunExport(runId, exportId)
  const name = filename || result.filename || '查询结果.xlsx'
  if (typeof document === 'undefined') return { ...result, filename: name }
  const url = URL.createObjectURL(result.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
  return { ...result, filename: name }
}
