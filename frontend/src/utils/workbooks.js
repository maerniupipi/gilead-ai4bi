export const MAX_WORKBOOKS = 10
export const MAX_WORKBOOK_BYTES = 10 * 1024 * 1024

export function validateWorkbookSelection(files, existingCount = 0) {
  if (files.length + existingCount > MAX_WORKBOOKS) return `最多上传 10 个 XLSX 文件，目前已有 ${existingCount} 个，请减少所选文件或先移除文件。`
  for (const file of files) {
    if (!/\.xlsx$/i.test(file.name || '')) return `「${file.name}」格式不支持，请选择 .xlsx 文件。`
    if (!file.size) return `「${file.name}」为空文件，请重新选择。`
    if (file.size > MAX_WORKBOOK_BYTES) return `「${file.name}」超过 10 MB，请缩小后上传。`
  }
  return ''
}

export function formatWorkbookSize(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`
}

export function workbookUploadId() {
  const values = new Uint32Array(4)
  globalThis.crypto.getRandomValues(values)
  return `upload_${Array.from(values, value => value.toString(16).padStart(8, '0')).join('')}`
}

const connectionError = error => !error?.status || error.status >= 500
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

export function workbookUploadErrorMessage(error) {
  return connectionError(error)
    ? '连接暂时中断，已接收的文件会继续处理。请恢复网络后刷新页面查看上传状态。'
    : error.message
}

export async function waitForWorkbookUpload(upload, {
  lookup, isCurrent = () => true, onStatus = () => {}, sleep = pause, maxPolls = 400,
}) {
  let failures = 0
  for (let index = 0; index < maxPolls && isCurrent(); index += 1) {
    if (upload.status === 'ready') return upload.workbook
    if (upload.status === 'failed' || upload.status === 'removed') {
      const error = new Error(upload.error || '文件已移除，请重新选择上传')
      error.status = 422
      throw error
    }
    onStatus(upload.status === 'queued' ? '已接收，正在排队解析' : '正在解析工作表，大文件需要一些时间')
    await sleep(1500)
    if (!isCurrent()) return null
    try {
      upload = await lookup(upload.id)
      if (!isCurrent()) return null
      failures = 0
    } catch (error) {
      if (!isCurrent()) return null
      if (!connectionError(error) || ++failures >= 5) throw error
      onStatus('连接恢复中，正在核对服务器处理状态')
    }
  }
  if (!isCurrent()) return null
  if (upload.status === 'ready') return upload.workbook
  const error = new Error('文件仍在后台处理中，请稍后刷新页面查看，无需重复上传。')
  error.status = 408
  throw error
}

export async function uploadWorkbookReliably(file, {
  begin, lookup, isCurrent = () => true, onStatus = () => {}, id = workbookUploadId(), ...options
}) {
  let upload
  for (let attempt = 0; attempt < 2 && isCurrent(); attempt += 1) {
    onStatus(attempt ? '正在恢复上传连接' : '正在传输文件')
    try {
      upload = await begin(file, id)
      break
    } catch (error) {
      if (!isCurrent()) return null
      if (!connectionError(error)) throw error
      onStatus('正在核对服务器是否已接收文件')
      try {
        upload = await lookup(id)
        break
      } catch (lookupError) {
        if (!isCurrent()) return null
        if (lookupError.status !== 404 && !connectionError(lookupError)) throw lookupError
        if (attempt === 1) throw error
        // Reuse the same ID: a lost response must never create a second workbook.
      }
    }
  }
  if (!isCurrent()) return null
  return waitForWorkbookUpload(upload, { lookup, isCurrent, onStatus, ...options })
}
