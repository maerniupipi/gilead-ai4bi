export const BOARD_THEMES = [
  { id: 'commercial', name: '商业经营', caption: '业绩、目标与增长驱动' },
  { id: 'behavior', name: '用户行为', caption: '活跃、转化与行为路径' },
  { id: 'general', name: '业务专题', caption: '汇集跨场景的业务发现' },
]
export const BOARD_ROLE_LABELS = { owner: '我创建的', editor: '可编辑', viewer: '可查看' }
export const canEditBoard = board => ['owner', 'editor'].includes(board?.my_role)
export const canManageBoard = board => board?.my_role === 'owner'
export const boardPath = id => `/workspace/${encodeURIComponent(id)}`
export const boardLink = id => `${location.origin}${location.pathname}#${boardPath(id)}`
export function scopeCaption(source) {
  const scope = source?.scope || {}
  const parts = [scope.label, scope.current_period, ({ qtd: '季度累计', ytd: '年度累计', mtd: '月度累计' })[scope.window],
    ...Object.values(scope.filters || {}).filter(Boolean)].filter(Boolean)
  return parts.length ? parts.join(' · ') : '保留收藏时的数据范围'
}
export function filterBoards(boards, search, tab) {
  return boards.filter(board => (!search.trim() || `${board.name} ${board.description}`.toLowerCase().includes(search.trim().toLowerCase()))
    && (tab === 'all' || (tab === 'mine' ? board.my_role === 'owner' : board.my_role !== 'owner')))
}
