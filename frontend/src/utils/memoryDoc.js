// The memory store keeps one row per remembered fact so each can be versioned,
// cited and revoked on its own. The page shows those rows as the one document
// they add up to — a heading per category, a bullet per fact — and turns an
// edited document back into row-level writes, so editing a bullet keeps that
// row's history instead of replacing it with a new row.

export const CATEGORY_LABELS = {
  preference: '偏好',
  metric_definition: '指标口径',
  scope: '默认范围',
  terminology: '术语',
  recent: '最近提问',
}

const CATEGORY_KEYS = Object.fromEntries(
  Object.entries(CATEGORY_LABELS).map(([key, label]) => [label, key]),
)
const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS)

export const TEMPLATE = `## 偏好
- 例：回答先给结论，再列口径和过滤条件。

## 指标口径
- 例：销售额默认指人民币出库金额，不含税。

## 默认范围
- 例：没有指明时间时，默认按当年 YTD。

## 术语
- 例：我说“大盘”指全国合计，不是所在辖区。

## 最近提问
- 例：问过的业务问题会出现在这里。
`

export function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category
}

export function sortEntries(entries) {
  const rank = (category) => {
    const index = CATEGORY_ORDER.indexOf(category)
    return index === -1 ? CATEGORY_ORDER.length : index
  }
  return [...entries].sort(
    (left, right) =>
      rank(left.category) - rank(right.category) ||
      String(left.created_at).localeCompare(String(right.created_at)),
  )
}

export function compose(entries) {
  const lines = []
  let heading = null
  for (const entry of entries) {
    if (entry.category !== heading) {
      heading = entry.category
      if (lines.length) lines.push('')
      lines.push(`## ${categoryLabel(heading)}`)
    }
    const [first, ...rest] = entry.content.split('\n')
    lines.push(`- ${first}`)
    lines.push(...rest.map((line) => `  ${line.trim()}`))
  }
  return lines.length ? lines.join('\n') + '\n' : ''
}

// A bullet opens an item; an indented line continues the one above it. Text
// outside any heading lands in 偏好, which is what the write API defaults to.
export function parse(markdown) {
  const items = []
  let category = CATEGORY_ORDER[0]
  for (const raw of String(markdown).split('\n')) {
    const heading = raw.match(/^#{1,4}\s+(.+?)\s*$/)
    if (heading) {
      const title = heading[1].replace(/\s*#+\s*$/, '')
      category = CATEGORY_KEYS[title] || title.slice(0, 64)
      continue
    }
    const bullet = raw.match(/^\s{0,3}[-*]\s+(.+?)\s*$/)
    if (bullet) {
      items.push({ category, content: bullet[1] })
      continue
    }
    const text = raw.trim()
    if (!text) continue
    if (items.length && /^\s{2,}/.test(raw)) items[items.length - 1].content += '\n' + text
    else items.push({ category, content: text })
  }
  return items.filter((item) => item.content)
}

// Matching a bullet back to its row is what decides whether an edit keeps that
// row's history or starts a new row. Untouched text claims its own row first, so
// reordering a section rewrites nothing; whatever is left over is matched by
// position within its category, which is how an edit in place stays an edit.
//
// The one thing position cannot tell apart is deleting one bullet and adding an
// unrelated one — that reads as an edit, and the deleted text ends up in the new
// row's version history rather than in a revoked row. The document still says
// exactly what the user typed, so this is a bookkeeping cost, not a wrong answer.
export function reconcile(wanted, existing) {
  const pools = new Map()
  for (const entry of existing) {
    if (!pools.has(entry.category)) pools.set(entry.category, [])
    pools.get(entry.category).push(entry)
  }
  const claimed = new Set()
  const matches = new Map()
  for (const item of wanted) {
    const same = (pools.get(item.category) || []).find(
      (entry) => !claimed.has(entry.id) && entry.content === item.content,
    )
    if (same) {
      claimed.add(same.id)
      matches.set(item, same)
    }
  }
  const plan = { create: [], update: [], revoke: [] }
  for (const item of wanted) {
    if (matches.has(item)) continue
    const free = (pools.get(item.category) || []).find((entry) => !claimed.has(entry.id))
    if (!free) {
      plan.create.push(item)
      continue
    }
    claimed.add(free.id)
    plan.update.push({ entry: free, content: item.content })
  }
  plan.revoke.push(...existing.filter((entry) => !claimed.has(entry.id)))
  return plan
}
