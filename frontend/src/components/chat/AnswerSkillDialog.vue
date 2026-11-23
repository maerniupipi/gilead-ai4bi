<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../../api/backend.js'
import { showToast, store } from '../../store.js'

const props = defineProps({ runId: { type: String, required: true } })
const emit = defineEmits(['close'])
const draft = ref({ name: '', blurb: '', prompt: '' })
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const dialog = ref(null)
let alive = true
let previousFocus = null
const valid = computed(() => draft.value.name.trim() && draft.value.prompt.trim().length >= 80 && !loading.value && !saving.value)

async function generate() {
  loading.value = true
  error.value = ''
  try {
    const result = await api.draftAnswerSkill(props.runId)
    if (alive) draft.value = result.draft
  } catch (reason) {
    if (alive) error.value = reason.message || '草稿生成失败，请重试'
  } finally {
    if (alive) loading.value = false
  }
}
async function save() {
  if (!valid.value) return
  saving.value = true
  error.value = ''
  try {
    const { item } = await api.createSkillPack({ ...draft.value, type: 'data_insight' })
    Object.assign(store.insightSkill, { skillPackId: item.id, skillName: item.name, customPrompt: '' })
    showToast(`已保存并加载「${item.name}」`)
    emit('close')
  } catch (reason) {
    error.value = reason.message || '保存失败'
  } finally { saving.value = false }
}
function keyboard(event) {
  if (event.key === 'Escape' && !saving.value) emit('close')
  if (event.key !== 'Tab') return
  const focusable = [...dialog.value.querySelectorAll('button:not(:disabled), input, textarea')]
  const first = focusable[0], last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(async () => {
  previousFocus = document.activeElement
  await nextTick()
  dialog.value?.focus()
  void generate()
})
onBeforeUnmount(() => { alive = false; previousFocus?.focus() })
</script>

<template>
  <Teleport to="body">
    <div class="veil skill-draft-veil" @click.self="!saving && emit('close')">
      <section ref="dialog" class="modal answer-skill-dialog" role="dialog" aria-modal="true" aria-labelledby="skill-draft-title" tabindex="-1" @keydown="keyboard">
        <header class="skill-draft-header">
          <div><span class="eyebrow">KNOWLEDGE → SKILL</span><h3 id="skill-draft-title">将这次分析，沉淀为方法</h3></div>
          <button type="button" class="draft-close" aria-label="关闭技能草稿" :disabled="saving" @click="emit('close')">×</button>
        </header>
        <p class="draft-intro">保留分析路径、指标口径与报告结构。下次加载时，按新的问题重新查数。</p>
        <div v-if="loading" class="draft-loading" role="status"><span class="draft-spinner"></span>正在提炼取数方法、下钻步骤和呈现方式…</div>
        <template v-else-if="draft.prompt">
          <label class="field"><span>技能名称</span><input v-model="draft.name" maxlength="160" /></label>
          <label class="field"><span>适用场景</span><input v-model="draft.blurb" maxlength="2000" /></label>
          <label class="field"><span>分析方法 <small>可在保存前编辑</small></span><textarea v-model="draft.prompt" rows="13" maxlength="50000" spellcheck="false"></textarea></label>
        </template>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <footer class="draft-footer">
          <span>保存后可在「加载模板」中复用</span>
          <button v-if="!loading && !draft.prompt" class="btn-s" type="button" @click="generate">重新生成</button>
          <button class="btn-p" type="button" :disabled="!valid" @click="save">{{ saving ? '正在保存…' : '保存并加载技能' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.skill-draft-veil { z-index: 160; backdrop-filter: blur(12px); }
.answer-skill-dialog { width: min(760px, calc(100vw - 32px)); max-height: 90dvh; overflow: auto; padding: 28px; border-radius: 24px; outline: none; }
.skill-draft-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.skill-draft-header h3 { margin: 8px 0 0; font-size: 23px; letter-spacing: -.04em; }
.draft-close { border: 0; background: #f3f3f5; color: var(--ink-2); width: 32px; height: 32px; border-radius: 50%; font-size: 24px; cursor: pointer; }
.draft-intro { color: var(--ink-2); line-height: 1.7; font-size: 13px; margin: 14px 0 22px; }
.field { display: grid; margin-top: 16px; gap: 8px; }
.field small { float: right; font-weight: 400; color: var(--ink-3); }
.field textarea { min-height: 260px; padding: 14px; line-height: 1.75; resize: vertical; border: 1px solid var(--line-strong); border-radius: 12px; background: #fafafb; color: var(--ink); font: 13px/1.75 var(--body-font); }
.draft-footer { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 22px; }
.draft-footer > span { flex: 1; font-size: 12px; color: var(--ink-3); }
.draft-loading { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 220px; color: var(--ink-2); font-size: 13px; }
.draft-spinner { width: 18px; height: 18px; border: 2px solid var(--accent-soft); border-top-color: var(--accent); border-radius: 50%; animation: draft-spin 1s linear infinite; }
@keyframes draft-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .draft-spinner { animation: none; } }
</style>
