export const LABS = [
  { lab_id: 'actual', name: '吉利德 DDI', description: 'DDI 销售金额/数量、达成、同环比、MTD' },
  { lab_id: 'demand', name: 'Demand', description: '需求计划与预测分析' },
  { lab_id: 'ext_simple', name: '外部数据 · 简单', description: '外部数据的基础查询' },
  { lab_id: 'ext_complex', name: '外部数据 · 复杂', description: '外部数据的综合分析' },
]

/** Map Bootcamp/compat lab_id to the business name shown in UI. */
export function labDisplayName(labId) {
  const id = String(labId || '').trim()
  if (!id) return ''
  const hit = LABS.find(item => item.lab_id === id)
  return hit?.name || id
}

/** Rewrite stored trace text that still embeds raw lab_id (e.g. 实验室：actual). */
export function rewriteLabLabelsInText(text) {
  let next = String(text || '')
  for (const lab of LABS) {
    if (!lab.lab_id || lab.lab_id === lab.name) continue
    next = next.replace(
      new RegExp(`(实验室\\s*[:：]\\s*)${lab.lab_id}\\b`, 'g'),
      `$1${lab.name}`,
    )
    next = next.replace(
      new RegExp(`(实验室\\s+)${lab.lab_id}\\b`, 'g'),
      `$1${lab.name}`,
    )
    next = next.replace(
      new RegExp(`\\b${lab.lab_id}(\\s*实验室)`, 'g'),
      `${lab.name}$1`,
    )
  }
  return next
}

export function createLabProfile(profile = {}) {
  return {
    endpoint_url: profile.endpoint_url || '',
    timeout_seconds: profile.timeout_seconds ?? 120,
    authorization: '',
    token_configured: Boolean(profile.token_configured),
    user_id: profile.user_id ?? 1,
    space_id: profile.space_id ?? 1,
    labs: LABS.map(lab => {
      const saved = profile.labs?.find(item => item.lab_id === lab.lab_id)
      return {
        ...lab,
        name: saved?.name || lab.name,
        api_access_id: saved?.api_access_id || '',
        credential_configured: Boolean(saved?.credential_configured),
        token: '',
      }
    }),
  }
}

export function labConnectionPayload(provider, mockEnabled, profile) {
  const next = {
    provider,
    endpoint_url: profile.endpoint_url.trim(),
    timeout_seconds: Number(profile.timeout_seconds),
    labs: profile.labs.map(lab => {
      const nextLab = { lab_id: lab.lab_id }
      if (provider === 'bootcamp') nextLab.api_access_id = lab.api_access_id.trim()
      else if (lab.token.trim()) nextLab.token = lab.token.trim()
      return nextLab
    }),
  }
  if (provider === 'bootcamp') {
    next.user_id = Number(profile.user_id)
    next.space_id = Number(profile.space_id)
    if (profile.authorization.trim()) next.authorization = profile.authorization.trim()
  }
  return { active_provider: provider, mock_enabled: Boolean(mockEnabled), profile: next }
}

export function labProfileChanged(provider, profile, savedProfile) {
  return JSON.stringify(labConnectionPayload(provider, false, profile).profile)
    !== JSON.stringify(labConnectionPayload(provider, false, createLabProfile(savedProfile)).profile)
}

export function configuredLabs(provider, mockEnabled, profile) {
  if (mockEnabled) return profile.labs
  return profile.labs.filter(lab => provider === 'bootcamp'
    ? Boolean(lab.api_access_id.trim())
    : Boolean(lab.credential_configured || lab.token.trim()))
}
