const META_KEY = 'xiaoying.eval.meta.v2'
const EVAL_DB = 'xiaoying.eval.v1'
const EVAL_STORE = 'state'

export function saveEvalMeta(meta) {
  try {
    localStorage.setItem(META_KEY, JSON.stringify(meta))
  } catch { /* quota/private mode */ }
}

export function loadEvalMeta() {
  try {
    return JSON.parse(localStorage.getItem(META_KEY) || 'null')
  } catch {
    return null
  }
}

export function clearEvalMeta() {
  try {
    localStorage.removeItem(META_KEY)
  } catch { /* private mode */ }
}

export async function clearEvalStore() {
  clearEvalMeta()
  if (typeof indexedDB === 'undefined') return
  await new Promise((resolve) => {
    const req = indexedDB.deleteDatabase(EVAL_DB)
    req.onsuccess = () => resolve()
    req.onerror = () => resolve()
    req.onblocked = () => resolve()
  })
}

export async function dropLegacyEvalCache() {
  if (typeof indexedDB === 'undefined') return
  try {
    const db = await new Promise((resolve, reject) => {
      const req = indexedDB.open(EVAL_DB, 1)
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(EVAL_STORE)) {
          req.result.createObjectStore(EVAL_STORE)
        }
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })
    await new Promise((resolve) => {
      if (!db.objectStoreNames.contains(EVAL_STORE)) {
        db.close()
        resolve()
        return
      }
      const tx = db.transaction(EVAL_STORE, 'readwrite')
      tx.objectStore(EVAL_STORE).delete('current')
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
    db.close()
  } catch {
    /* ignore legacy cache errors */
  }
}
