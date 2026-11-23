<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api/backend.js'
import { applyBrandingToDocument, mergeBranding } from '../branding.js'
import { loadBranding, showToast, store } from '../store.js'

const loading = ref(true)
const saving = ref(false)
const uploading = ref(false)
const fileInput = ref(null)
const form = reactive({
  character_name: '',
  company_intro: '',
  theme_id: 'azalea',
  logo_kind: 'preset',
  logo_preset_id: 'xiaoying',
  logo_url: '/brand/gilead-bi.svg',
})

const themes = computed(() => store.branding.themes || [])
const logos = computed(() => store.branding.logos || [])
const currentTheme = computed(() => themes.value.find(item => item.id === form.theme_id) || themes.value[0])
const previewLogo = computed(() => {
  if (form.logo_kind === 'upload' && form.logo_url) return form.logo_url
  return logos.value.find(item => item.id === form.logo_preset_id)?.url || form.logo_url || '/brand/gilead-bi.svg'
})
const previewName = computed(() => form.character_name.trim() || 'Gilead BI')
const previewIntro = computed(() => form.company_intro.trim() || '业务助手')

function hydrate(payload) {
  form.character_name = payload.character_name || ''
  form.company_intro = payload.company_intro || ''
  form.theme_id = payload.theme_id || 'azalea'
  form.logo_kind = payload.logo_kind || 'preset'
  form.logo_preset_id = payload.logo_preset_id || 'xiaoying'
  form.logo_url = payload.logo_url || '/brand/gilead-bi.svg'
}

function previewDocument() {
  const theme = currentTheme.value
  applyBrandingToDocument(mergeBranding({
    ...store.branding,
    character_name: previewName.value,
    company_intro: previewIntro.value,
    theme_id: form.theme_id,
    logo_url: previewLogo.value,
    tokens: theme?.tokens || store.branding.tokens,
  }))
}

watch(
  () => [form.character_name, form.company_intro, form.theme_id, form.logo_kind, form.logo_preset_id, form.logo_url],
  previewDocument,
)

function pickLogo(logo) {
  form.logo_kind = 'preset'
  form.logo_preset_id = logo.id
  form.logo_url = logo.url
}

async function onUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || uploading.value) return
  uploading.value = true
  try {
    const payload = await api.uploadBrandingLogo(file)
    store.branding = mergeBranding(payload)
    form.logo_kind = payload.logo_kind
    form.logo_preset_id = payload.logo_preset_id
    form.logo_url = payload.logo_url
    showToast('人物头像已更新')
  } catch (error) {
    showToast('上传失败：' + error.message)
  } finally {
    uploading.value = false
  }
}

async function save() {
  if (saving.value) return
  const name = form.character_name.trim()
  const intro = form.company_intro.trim()
  if (!name || !intro) {
    showToast('请填写人物名称和公司介绍')
    return
  }
  saving.value = true
  try {
    const body = {
      character_name: name,
      company_intro: intro,
      theme_id: form.theme_id,
    }
    if (form.logo_kind === 'preset') body.logo_preset_id = form.logo_preset_id
    const payload = await api.updateBranding(body)
    store.branding = mergeBranding(payload)
    hydrate(payload)
    applyBrandingToDocument(store.branding)
    showToast('品牌配置已保存，当前部署的用户都会看到这套形象')
  } catch (error) {
    showToast('保存失败：' + error.message)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadBranding()
    hydrate(store.branding)
  } catch (error) {
    showToast('品牌配置加载失败：' + error.message)
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  applyBrandingToDocument(store.branding)
})
</script>

<template>
  <div class="page-shell wide-page">
    <header class="page-head">
      <div>
        <div class="eyebrow">交付</div>
        <h1>品牌配置</h1>
        <p>给当前客户配置人物形象、名称、介绍和主题色。这是整套产品对外露出的门面，保存后立刻生效。</p>
      </div>
      <button class="btn-p" type="button" :disabled="saving || loading" @click="save">{{ saving ? '正在保存…' : '保存配置' }}</button>
    </header>

    <div v-if="loading" class="loading-state">正在读取当前品牌…</div>
    <div v-else class="brand-layout">
      <div class="brand-main">
        <section class="panel brand-card">
          <div class="panel-head">
            <div><span>对外名称</span><h2>人物与介绍</h2></div>
          </div>
          <div class="form-grid">
            <label class="field">
              <span>人物名称</span>
              <input v-model="form.character_name" maxlength="32" placeholder="例如：Gilead BI" />
            </label>
            <label class="field">
              <span>公司介绍</span>
              <input v-model="form.company_intro" maxlength="64" placeholder="例如：吉利德业务助手" />
            </label>
          </div>
        </section>

        <section class="panel brand-card">
          <div class="panel-head">
            <div>
              <span>人物形象</span>
              <h2>选择或上传 Logo</h2>
            </div>
            <button class="btn-g" type="button" :disabled="uploading" @click="fileInput?.click()">{{ uploading ? '正在上传…' : '上传自定义' }}</button>
            <input ref="fileInput" class="file-hidden" type="file" accept="image/png,image/jpeg,image/webp" @change="onUpload" />
          </div>
          <p class="form-hint logo-hint">内置 11 个形象，风格和小英一致。也可以上传 PNG / JPEG / WebP，不超过 2MB。</p>
          <div class="logo-grid">
            <button
              v-for="logo in logos"
              :key="logo.id"
              type="button"
              class="logo-tile"
              :class="{ on: form.logo_kind === 'preset' && form.logo_preset_id === logo.id }"
              @click="pickLogo(logo)"
            >
              <img :src="logo.url" :alt="logo.name" />
              <strong>{{ logo.name }}</strong>
              <span>{{ logo.description }}</span>
            </button>
            <button
              v-if="form.logo_kind === 'upload'"
              type="button"
              class="logo-tile on upload-tile"
            >
              <img :src="form.logo_url" alt="自定义头像" />
              <strong>自定义</strong>
              <span>已上传</span>
            </button>
          </div>
        </section>

        <section class="panel brand-card">
          <div class="panel-head">
            <div><span>主题色</span><h2>五种内置主题</h2></div>
          </div>
          <div class="theme-grid">
            <button
              v-for="theme in themes"
              :key="theme.id"
              type="button"
              class="theme-card"
              :class="{ on: form.theme_id === theme.id }"
              @click="form.theme_id = theme.id"
            >
              <span class="theme-swatch" :style="{ background: theme.tokens.accent }"></span>
              <span class="theme-soft" :style="{ background: theme.tokens['accent-soft'] }"></span>
              <strong>{{ theme.name }}</strong>
              <span>{{ theme.description }}</span>
            </button>
          </div>
        </section>
      </div>

      <aside class="brand-preview panel">
        <div class="preview-kicker">实时预览</div>
        <div class="preview-stage">
          <div class="preview-brand">
            <img :src="previewLogo" :alt="previewName" />
            <div>
              <strong>{{ previewName }}</strong>
              <span>{{ previewIntro }}</span>
            </div>
          </div>
          <div class="preview-hero">
            <img :src="previewLogo" :alt="previewName" />
            <p>嗨，我是{{ previewName }}</p>
            <h3>有问题先交给我。</h3>
            <small>{{ previewIntro }}</small>
          </div>
          <button class="preview-cta" type="button">和{{ previewName }}聊</button>
        </div>
        <p class="preview-note">预览会暂时作用到左侧菜单和标题；离开本页且未保存时，会恢复成已保存的配置。</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.brand-layout {
  align-items: start;
  display: grid;
  gap: 22px;
  grid-template-columns: minmax(0, 1fr) 320px;
  margin: 0 auto;
  max-width: 1120px;
}
.brand-main { display: grid; gap: 18px; min-width: 0; }
.brand-card { padding: 18px 20px 20px; }
.logo-hint { margin: -4px 0 14px; }
.file-hidden { display: none; }
.logo-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
}
.logo-tile {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  display: grid;
  gap: 4px;
  justify-items: center;
  padding: 12px 8px 10px;
  text-align: center;
}
.logo-tile img {
  border-radius: 50%;
  height: 64px;
  object-fit: cover;
  width: 64px;
}
.logo-tile strong { font-size: 13px; font-weight: 650; }
.logo-tile span { color: var(--ink-3); font-size: 11px; }
.logo-tile.on {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), .12);
}
.theme-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}
.theme-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  display: grid;
  gap: 6px;
  padding: 12px;
  text-align: left;
}
.theme-card.on {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), .12);
}
.theme-swatch { border-radius: 999px; display: block; height: 8px; width: 100%; }
.theme-soft { border-radius: 8px; display: block; height: 28px; }
.theme-card strong { font-size: 14px; }
.theme-card span:last-child { color: var(--ink-3); font-size: 12px; line-height: 1.45; }
.brand-preview { padding: 18px; position: sticky; top: 12px; }
.preview-kicker { color: var(--accent); font-size: 12px; font-weight: 650; margin-bottom: 12px; }
.preview-stage {
  background:
    radial-gradient(180px 80px at 90% 0%, rgba(var(--accent-rgb), .12), transparent 70%),
    var(--bg);
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
  padding: 16px;
}
.preview-brand { align-items: center; display: flex; gap: 10px; margin-bottom: 16px; }
.preview-brand img { border-radius: 50%; height: 38px; object-fit: cover; width: 38px; }
.preview-brand strong { display: block; font-size: 15px; line-height: 1.2; }
.preview-brand span { color: var(--ink-3); font-size: 11px; }
.preview-hero {
  background: var(--paper);
  border-radius: 16px;
  display: grid;
  justify-items: center;
  padding: 22px 16px 18px;
  text-align: center;
}
.preview-hero img { border-radius: 50%; height: 72px; object-fit: cover; width: 72px; }
.preview-hero p { color: var(--accent); font-size: 13px; font-weight: 650; margin-top: 10px; }
.preview-hero h3 { font-size: 18px; letter-spacing: -.02em; margin-top: 4px; }
.preview-hero small { color: var(--ink-3); font-size: 12px; margin-top: 6px; }
.preview-cta {
  background: var(--accent);
  border: 0;
  border-radius: 12px;
  color: white;
  font-weight: 650;
  margin-top: 12px;
  min-height: 38px;
  width: 100%;
}
.preview-note { color: var(--ink-3); font-size: 12px; line-height: 1.5; margin-top: 12px; }
@media (max-width: 960px) {
  .brand-layout { grid-template-columns: 1fr; }
  .brand-preview { position: static; }
}
</style>
