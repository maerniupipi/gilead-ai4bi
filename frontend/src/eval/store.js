import { computed, markRaw, reactive, shallowReactive, shallowRef } from 'vue'
import { api } from '../api/backend.js'
import { showToast, store } from '../store.js'
import {
  TERMINAL,
  EVAL_EVENT_PAGE_SIZE,
  canRerun,
  clearItemResult,
  concurrencyOf,
  consumeEventPage,
  formatClarifications,
  formatDuration,
  isQueued,
  lightenItem,
  modelOptions,
  normalizeEvalSettings,
  persistableValues,
  recommendedAnswers,
  rebuildItems,
  stampResult,
  statusLabel,
  summaryToPrior,
} from './format.js'
import { clearEvalStore, dropLegacyEvalCache, loadEvalMeta, saveEvalMeta } from './persist.js'

const controllers = new Map()
const PAGE_SIZE = 80
const PERSIST_ATTEMPTS = 3
const POLL_INTERVAL_MS = 60_000
let saveTimer = 0
let unloadGuardOn = false

function unloadHandler(event) {
  event.preventDefault()
  event.returnValue = '评测还在跑，关闭页面会中断未完成的题目。已完成的题已写入数据库。'
}

function setUnloadGuard(on) {
  if (on === unloadGuardOn) return
  unloadGuardOn = on
  if (on) window.addEventListener('beforeunload', unloadHandler)
  else window.removeEventListener('beforeunload', unloadHandler)
}

export const evalItems = shallowRef([])
export const evalWorkbook = shallowRef(null)

export const evalState = reactive({
  logs: ['等待开始。'],
  running: false,
  pausing: false,
  stop: false,
  inFlight: 0,
  soloRuns: 0,
  restored: false,
  hydrating: false,
  page: 1,
  pageSize: PAGE_SIZE,
  batchId: '',
  settings: normalizeEvalSettings(),
})

function toRow(item) {
  return shallowReactive({
    ...item,
    values: { ...(item.values || {}) },
  })
}

function setItems(list) {
  evalItems.value = list.map(toRow)
  const pages = Math.max(1, Math.ceil(evalItems.value.length / evalState.pageSize))
  if (evalState.page > pages) evalState.page = pages
}

export const evalBusy = computed(() => evalState.running || evalState.soloRuns > 0)
export const evalStats = computed(() => {
  const items = evalItems.value
  const total = items.length
  const done = items.filter((item) => item.status === 'done').length
  const fail = items.filter((item) => item.status === 'failed').length
  const queued = items.filter(isQueued).length
  return {
    total,
    done,
    fail,
    queued,
    now: evalBusy.value ? `${evalState.inFlight} 路并行` : '—',
    meter: total ? Math.round(((done + fail) / total) * 100) : 0,
    pages: Math.max(1, Math.ceil(total / evalState.pageSize)),
  }
})
export const pagedItems = computed(() => {
  const start = (evalState.page - 1) * evalState.pageSize
  return evalItems.value.slice(start, start + evalState.pageSize)
})
export const fileMeta = computed(() => {
  const workbook = evalWorkbook.value
  if (!workbook) return ''
  const total = workbook.sheets.reduce((n, sheet) => n + sheet.question_count, 0)
  return `${workbook.filename} · ${workbook.sheets.length} 表 · ${total} 题`
})

function uuid() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForNextPoll(ms, signal) {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    if (evalState.stop || signal?.aborted) return
    await sleep(Math.min(1000, deadline - Date.now()))
  }
}

export function logEval(line) {
  const stamp = new Date().toLocaleTimeString()
  evalState.logs.push(`[${stamp}] ${line}`)
  if (evalState.logs.length > 400) evalState.logs.splice(0, evalState.logs.length - 400)
}

function snapshotMeta() {
  return {
    batchId: evalState.batchId,
    filename: evalWorkbook.value?.filename || '',
    settings: { ...evalState.settings, selectedSheets: [...evalState.settings.selectedSheets] },
    savedAt: Date.now(),
  }
}

export function saveEval() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveEvalMeta(snapshotMeta())
  }, 200)
}

export async function saveEvalNow() {
  clearTimeout(saveTimer)
  saveEvalMeta(snapshotMeta())
}

export function rebuildQueue({ persist = true, previousItems } = {}) {
  if (!evalWorkbook.value) {
    setItems([])
    return
  }
  const selected = evalState.settings.selectedSheets.length
    ? evalState.settings.selectedSheets
    : evalWorkbook.value.sheets.map((sheet) => sheet.name)
  setItems(rebuildItems({
    workbook: evalWorkbook.value,
    selectedSheetNames: selected,
    fromIndex: evalState.settings.fromIndex,
    toIndex: evalState.settings.toIndex,
    previousItems: previousItems || evalItems.value,
  }))
  if (persist) saveEval()
}

async function loadBatchSummaries() {
  if (!evalState.batchId || !store.token) return []
  try {
    const payload = await api.listEvalResults(evalState.batchId)
    return (payload.items || []).map(summaryToPrior)
  } catch (error) {
    logEval(`读取已落库结果失败：${error.message || error}`)
    return []
  }
}

async function persistItem(item) {
  if (!evalState.batchId) return false
  const body = {
    sheet: item.sheet,
    row: item.row,
    question: item.question,
    category: item.category,
    status: item.status,
    clarify: item.clarify || '',
    sql: item.sql || '',
    labs: item.labs || '',
    answer: item.answer || '',
    duration: item.duration || '',
    run_id: item.runId || '',
    error: item.error || '',
    headers: item.headers || [],
    values: persistableValues(item),
  }
  for (let attempt = 1; attempt <= PERSIST_ATTEMPTS; attempt += 1) {
    try {
      const saved = await api.upsertEvalResult(evalState.batchId, body)
      lightenItem(item, saved?.answer_preview || item.error || '')
      return true
    } catch (error) {
      if (error?.status === 401 || error?.status === 403) {
        logEval(`落库失败：${error.message || error}`)
        return false
      }
      if (attempt >= PERSIST_ATTEMPTS) {
        logEval(`落库失败：${error.message || error}。刷新后这题会回到待跑，可再跑一次。`)
        return false
      }
      logEval(`落库失败（第 ${attempt} 次），准备重试：${error.message || error}`)
      await sleep(400 * attempt)
    }
  }
  return false
}

export async function loadItemDetail(item) {
  if (!item || !evalState.batchId) return item
  if (item.sql || item.clarify || item.labs) return item
  if (item.status !== 'done' && item.status !== 'failed') return item
  try {
    const detail = await api.getEvalResult(evalState.batchId, item.sheet, item.row)
    item.clarify = detail.clarify || ''
    item.sql = detail.sql || ''
    item.labs = detail.labs || ''
    item.answer = detail.answer || item.answer
    return item
  } catch (error) {
    logEval(`读取题目详情失败：${error.message || error}`)
    return item
  }
}

export function forgetItemDetail(item) {
  if (!item) return
  lightenItem(item, item.error || (item.status === 'done' ? '已落库' : ''))
}

export function toggleSheet(name, checked) {
  const current = new Set(evalState.settings.selectedSheets)
  if (checked) current.add(name)
  else current.delete(name)
  evalState.settings.selectedSheets = [...current]
  rebuildQueue()
}

export async function restoreEval() {
  if (evalState.restored) return
  evalState.restored = true
  evalState.hydrating = true
  try {
    await dropLegacyEvalCache()
    const saved = loadEvalMeta()
    if (!saved) return
    Object.assign(evalState.settings, normalizeEvalSettings(saved.settings || {}))
    evalState.batchId = saved.batchId || ''
    if (evalState.batchId) {
      logEval('已记住上次评测批次。重新上传工作簿后会从数据库合并完成状态，不回放本机大文件。')
    }
  } catch (error) {
    logEval(`恢复评测设置失败：${error.message || error}`)
  } finally {
    evalState.hydrating = false
  }
}

export async function uploadWorkbook(file) {
  if (!file) return
  if (!store.token) {
    store.loginOpen = true
    showToast('请先登录再上传')
    return
  }
  try {
    evalWorkbook.value = markRaw(await api.parseEvalWorkbook(file))
    if (!evalState.batchId) {
      try {
        const batch = await api.createEvalBatch(evalWorkbook.value.filename)
        evalState.batchId = batch.id
      } catch (error) {
        logEval(`创建评测批次失败：${error.message || error}。题目仍可跑，完成后不会写入数据库。`)
      }
    }
    evalState.settings.selectedSheets = evalWorkbook.value.sheets.map((sheet) => sheet.name)
    evalState.page = 1
    const previous = await loadBatchSummaries()
    setItems([])
    rebuildQueue({ persist: false, previousItems: previous })
    await saveEvalNow()
    logEval(`已解析 ${evalWorkbook.value.filename}，结果将逐题写入数据库。`)
  } catch (error) {
    showToast(error.message || '解析失败')
  }
}

export async function clearWorkbook() {
  clearTimeout(saveTimer)
  await clearEvalStore()
  evalWorkbook.value = null
  evalState.batchId = ''
  setItems([])
  evalState.settings.selectedSheets = []
  evalState.page = 1
  logEval('已清空当前评测队列。数据库里的历史结果仍保留，可用同一批次导出。')
  showToast('已清空 xlsx')
}

export function setEvalPage(page) {
  const pages = Math.max(1, Math.ceil(evalItems.value.length / evalState.pageSize))
  evalState.page = Math.min(pages, Math.max(1, Number(page) || 1))
}

async function catchUp(runId, after, collected, signal) {
  let cursor = Number(after || 0)
  for (;;) {
    const page = await api.runEvents(runId, { after: cursor, limit: EVAL_EVENT_PAGE_SIZE }, { signal })
    const items = page?.items || []
    const next = consumeEventPage(collected, cursor, page)
    if (!items.length || next <= cursor) return cursor
    cursor = next
    if (!page?.has_more) return cursor
  }
}

async function answerClarify(payload, collected, item, signal) {
  if (!payload?.case_id || !payload.groups?.length) return
  collected.answeredCases = collected.answeredCases || new Set()
  if (collected.answeredCases.has(payload.case_id)) return
  collected.answeredCases.add(payload.case_id)
  const { answers, records } = recommendedAnswers(payload.groups)
  if (!answers.length) throw new Error('澄清没有可选项')
  collected.clarifications.push(...records)
  item.clarify = formatClarifications(collected.clarifications)
  await api.clarify(payload.case_id, answers, modelOptions(evalState.settings), { signal })
}

async function followRun(accepted, collected, item, signal) {
  let cursor = 0
  collected.answeredCases = collected.answeredCases || new Set()
  const deadline = Date.now() + 45 * 60 * 1000
  while (Date.now() < deadline) {
    if (evalState.stop) throw new Error('已停止')
    if (signal?.aborted) throw new Error('已停止')
    cursor = await catchUp(accepted.run_id, cursor, collected, signal)
    if (TERMINAL.has(collected.status)) return
    if (collected.pendingClarify) {
      const clarify = collected.pendingClarify
      collected.pendingClarify = null
      item.status = 'clarify'
      await answerClarify(clarify, collected, item, signal)
      collected.status = 'running'
      continue
    }
    const run = await api.run(accepted.run_id, { signal })
    collected.status = run.status || collected.status
    if (TERMINAL.has(collected.status)) {
      await catchUp(accepted.run_id, cursor, collected, signal)
      return
    }
    if (run.status === 'waiting_clarification') {
      const waiting = await api.waitingClarifications({ run_id: accepted.run_id }, { signal })
      if (waiting?.length) {
        item.status = 'clarify'
        await answerClarify(waiting[0], collected, item, signal)
        collected.status = 'running'
        continue
      }
    }
    await waitForNextPoll(POLL_INTERVAL_MS, signal)
  }
  throw new Error('等待结果超时')
}

async function runItem(item) {
  item.status = 'running'
  item.error = ''
  evalState.inFlight += 1
  const started = Date.now()
  const collected = { sqls: [], labs: [], recalls: [], clarifications: [], answer: '', status: 'running', error: '', seenCallIds: new Set() }
  const controller = new AbortController()
  controllers.set(item.id, controller)
  try {
    const accepted = await api.createChat(
      item.question,
      null,
      uuid(),
      modelOptions(evalState.settings),
      { signal: controller.signal },
    )
    item.runId = accepted.run_id
    collected.status = accepted.status || collected.status
    await followRun(accepted, collected, item, controller.signal)
    stampResult(item, collected)
  } catch (error) {
    item.status = 'failed'
    item.error = error.message || '评测失败'
    item.values['最终结果'] = item.error
    item.values['状态'] = statusLabel('failed')
  } finally {
    evalState.inFlight = Math.max(0, evalState.inFlight - 1)
    controllers.delete(item.id)
  }
  item.duration = formatDuration(Date.now() - started)
  item.values['持续时间'] = item.duration
  item.values['运行ID'] = item.runId
  await persistItem(item)
  saveEval()
  if (item.status === 'failed') logEval(`#${item.index} ${item.sheet} 失败：${item.error}`)
  else logEval(`#${item.index} ${item.sheet} 完成`)
}

async function runPool(workers, list) {
  let next = 0
  const runWorker = async () => {
    for (;;) {
      if (evalState.stop) return
      while (evalState.pausing && !evalState.stop) await sleep(200)
      if (evalState.stop) return
      const index = next
      next += 1
      if (index >= list.length) return
      const item = list[index]
      if (!isQueued(item)) continue
      await runItem(item)
    }
  }
  await Promise.all(Array.from({ length: workers }, runWorker))
}

export async function startEval() {
  if (!store.token) {
    store.loginOpen = true
    showToast('请先登录后跑评测')
    return
  }
  if (!evalItems.value.length) {
    showToast('请先上传工作簿并选择工作表')
    return
  }
  const remaining = evalItems.value.filter(isQueued)
  if (!remaining.length) {
    showToast('没有待跑题目。失败题请用「重跑失败项」。')
    return
  }
  evalState.running = true
  evalState.pausing = false
  evalState.stop = false
  setUnloadGuard(true)
  const workers = concurrencyOf(evalState.settings.concurrency)
  logEval(`开始评测：${workers} 路并行，待跑 ${remaining.length} 题`)
  try {
    await runPool(workers, remaining)
  } finally {
    evalState.running = false
    if (evalState.soloRuns === 0) setUnloadGuard(false)
  }
  logEval(evalState.stop ? '已停止。' : '评测结束。')
  showToast('评测结束')
  await saveEvalNow()
}

export function pauseEval() {
  evalState.pausing = !evalState.pausing
  logEval(evalState.pausing ? '进行中的题会跑完，不再开新题。' : '继续评测。')
}

export function stopEval() {
  evalState.stop = true
  evalState.pausing = false
  controllers.forEach((controller) => controller.abort())
  logEval('正在停止…')
}

export async function rerunOne(item) {
  if (!item || !canRerun(item)) return
  if (!store.token) {
    store.loginOpen = true
    return
  }
  if (!evalState.running) evalState.stop = false
  clearItemResult(item)
  evalState.soloRuns += 1
  setUnloadGuard(true)
  logEval(`单挑重跑 #${item.index} ${item.sheet}：${item.question.slice(0, 48)}`)
  try {
    await runItem(item)
  } finally {
    evalState.soloRuns = Math.max(0, evalState.soloRuns - 1)
    if (!evalState.running && evalState.soloRuns === 0) {
      evalState.stop = false
      setUnloadGuard(false)
    }
    await saveEvalNow()
  }
}

export async function rerunFailed() {
  if (!store.token) {
    store.loginOpen = true
    return
  }
  const failed = evalItems.value.filter((item) => item.status === 'failed' && canRerun(item))
  if (!failed.length) {
    showToast('没有失败项可重跑')
    return
  }
  if (!evalState.running) evalState.stop = false
  logEval(`重跑 ${failed.length} 道失败题。`)
  const workers = Math.min(concurrencyOf(evalState.settings.concurrency), failed.length)
  failed.forEach(clearItemResult)
  evalState.soloRuns += failed.length
  setUnloadGuard(true)
  try {
    await runPool(workers, failed)
  } finally {
    evalState.soloRuns = Math.max(0, evalState.soloRuns - failed.length)
    if (!evalState.running && evalState.soloRuns === 0) {
      evalState.stop = false
      setUnloadGuard(false)
    }
    await saveEvalNow()
  }
  showToast('失败项重跑结束')
}

export async function exportWorkbook() {
  if (!evalState.batchId) {
    showToast('还没有评测批次，请先上传并跑题')
    return
  }
  try {
    const blob = await api.exportEvalBatch(evalState.batchId)
    const filename = `${(evalWorkbook.value?.filename || '评测').replace(/\.xlsx$/i, '')}-结果.xlsx`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
    showToast('已导出')
  } catch (error) {
    showToast(error.message || '导出失败')
  }
}
