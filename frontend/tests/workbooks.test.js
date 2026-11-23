import test from 'node:test'
import assert from 'node:assert/strict'
import { MAX_WORKBOOK_BYTES, validateWorkbookSelection, formatWorkbookSize } from '../src/utils/workbooks.js'
import { uploadWorkbookReliably, waitForWorkbookUpload, workbookUploadErrorMessage, workbookUploadId } from '../src/utils/workbooks.js'

const file = (name = 'data.xlsx', size = 100) => ({ name, size })

test('XLSX count and size limits accept exact boundaries', () => {
  assert.equal(validateWorkbookSelection([file('DATA.XLSX', MAX_WORKBOOK_BYTES)], 9), '')
  assert.match(validateWorkbookSelection([file(), file()], 9), /最多上传 10/)
  assert.match(validateWorkbookSelection([file('big.xlsx', MAX_WORKBOOK_BYTES + 1)]), /超过 10 MB/)
})

const networkError = () => new TypeError('Failed to fetch')
const ready = { id: 'upload_test_123456', status: 'ready', workbook: { id: 'book1', row_count: 100000 } }
const queued = { id: ready.id, status: 'queued' }
const immediate = async () => {}

test('a lost upload response is reconciled with the saved server result', async () => {
  let submissions = 0
  const result = await uploadWorkbookReliably(file(), {
    id: ready.id,
    begin: async () => { submissions += 1; throw networkError() },
    lookup: async id => { assert.equal(id, ready.id); return ready },
  })
  assert.deepEqual(result, ready.workbook)
  assert.equal(submissions, 1)
})

test('an upload retry reuses its ID and polls until the server completes', async () => {
  const ids = [], progress = []
  let polls = 0
  const result = await uploadWorkbookReliably(file(), {
    id: ready.id, sleep: immediate,
    begin: async (_, id) => { ids.push(id); if (ids.length === 1) throw networkError(); return queued },
    lookup: async () => { if (++polls === 1) throw Object.assign(new Error('missing'), { status: 404 }); return ready },
    onStatus: message => progress.push(message),
  })
  assert.deepEqual(ids, [ready.id, ready.id])
  assert.equal(result.row_count, 100000)
  assert.ok(progress.some(message => message.includes('排队')))
})

test('a transient polling failure recovers without resubmitting the file', async () => {
  let polls = 0
  const progress = []
  const result = await waitForWorkbookUpload(queued, {
    sleep: immediate,
    lookup: async () => { if (++polls === 1) throw networkError(); return ready },
    onStatus: message => progress.push(message),
  })
  assert.equal(result.id, ready.workbook.id)
  assert.ok(progress.some(message => message.includes('连接恢复')))
})

test('server validation errors are retained and never retried as network failures', async () => {
  let lookups = 0
  const invalid = Object.assign(new Error('每个 XLSX 最多支持 5 个 sheet'), { status: 422 })
  await assert.rejects(uploadWorkbookReliably(file(), {
    id: ready.id, begin: async () => { throw invalid }, lookup: async () => { lookups += 1 },
  }), error => error === invalid)
  assert.equal(lookups, 0)
  await assert.rejects(waitForWorkbookUpload({ ...queued, status: 'failed', error: invalid.message }, {
    lookup: async () => ready,
  }), /5 个 sheet/)
  assert.equal(workbookUploadErrorMessage(invalid), invalid.message)
  assert.match(workbookUploadErrorMessage(networkError()), /恢复网络后刷新/)
})

test('switching accounts cancels polling and prevents another upload request', async () => {
  let current = true, lookups = 0
  const result = await waitForWorkbookUpload(queued, {
    isCurrent: () => current,
    sleep: async () => { current = false },
    lookup: async () => { lookups += 1; return ready },
  })
  assert.equal(result, null)
  assert.equal(lookups, 0)
  let starts = 0
  assert.equal(await uploadWorkbookReliably(file(), {
    id: ready.id, isCurrent: () => false,
    begin: async () => { starts += 1 }, lookup: async () => ready,
  }), null)
  assert.equal(starts, 0)
})

test('upload IDs work on HTTP hosts without crypto.randomUUID', () => {
  assert.match(workbookUploadId(), /^upload_[a-f0-9]{32}$/)
  assert.notEqual(workbookUploadId(), workbookUploadId())
})

test('unsupported and empty files are rejected before upload', () => {
  assert.match(validateWorkbookSelection([file('fake.xlsx.csv')]), /格式不支持/)
  assert.match(validateWorkbookSelection([file('empty.xlsx', 0)]), /为空文件/)
  assert.equal(formatWorkbookSize(1024), '1 KB')
  assert.equal(formatWorkbookSize(MAX_WORKBOOK_BYTES), '10.0 MB')
})
