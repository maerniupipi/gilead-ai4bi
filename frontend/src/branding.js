export const DEFAULT_BRANDING = {
  character_name: 'Gilead BI',
  company_intro: '商业智能分析平台',
  theme_id: 'gilead',
  logo_kind: 'preset',
  logo_preset_id: 'gilead-bi',
  logo_url: '/brand/gilead-bi.svg',
  tokens: {
    accent: '#c5203f',
    'accent-dark': '#881222',
    'accent-soft': '#fbedf0',
    'accent-rgb': '197, 32, 63',
    'accent-glow-rgb': '197, 32, 63',
    plum: '#242630',
    'plum-rgb': '36, 38, 48',
    navy: '#203662',
    cyan: '#3fb9c2',
    gold: '#c48a24',
    success: '#227257',
    danger: '#a63838',
    warning: '#986716',
    bg: '#f5f5f7',
    paper: '#ffffff',
    surface: '#ffffff',
    ink: '#242630',
    'ink-2': '#686a75',
    'ink-3': '#888a95',
    line: 'rgba(36, 38, 48, .08)',
    'line-strong': 'rgba(36, 38, 48, .14)',
    shadow: '0 10px 30px rgba(36, 38, 48, .06)',
    'shadow-lg': '0 22px 56px rgba(36, 38, 48, .12)',
    'composer-bg': '#ffffff',
  },
  themes: [],
  logos: [],
  updated_at: null,
}

export function applyBrandingToDocument(branding = DEFAULT_BRANDING) {
  const tokens = branding.tokens || DEFAULT_BRANDING.tokens
  const root = document.documentElement
  Object.entries(tokens).forEach(([key, value]) => {
    if (typeof value === 'string' && value) root.style.setProperty(`--${key}`, value)
  })
  if (branding.theme_id) root.dataset.theme = branding.theme_id
  const name = branding.character_name || DEFAULT_BRANDING.character_name
  const intro = branding.company_intro || DEFAULT_BRANDING.company_intro
  document.title = `${name} · ${intro}`
  const icon = document.querySelector('link[rel="icon"]')
  if (icon && branding.logo_url) icon.href = branding.logo_url
}

export function mergeBranding(payload) {
  return {
    ...DEFAULT_BRANDING,
    ...payload,
    tokens: { ...DEFAULT_BRANDING.tokens, ...(payload?.tokens || {}) },
    themes: payload?.themes || DEFAULT_BRANDING.themes,
    logos: payload?.logos || DEFAULT_BRANDING.logos,
  }
}
