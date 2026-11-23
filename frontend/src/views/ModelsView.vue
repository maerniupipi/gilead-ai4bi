<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, showToast } from '../store.js'

const configs = ref([])
const activeId = ref('')
const creating = ref(false)
const editingId = ref('')
const saving = ref(false)
const loading = ref(true)
const tests = reactive({})
const actionPending = reactive({})
const form = reactive(emptyForm())

function emptyForm() {
  return {
    name: '', endpoint_url: '', model_id: '', api_key: '',
    temperature: 0.2, max_tokens: 16384, reasoning: 'auto', timeout_seconds: 180,
    activate: false,
  }
}

function reasoningLabel(value) {
  return { auto: '自动', on: '开启', off: '关闭' }[value] || value
}

function paramSummary(source) {
  return `${source.temperature} · ${source.max_tokens} tokens · 思考${reasoningLabel(source.reasoning)} · ${source.timeout_seconds}s`
}

async function reload() {
  loading.value = true
  try {
    const result = await api.modelConfigs()
    configs.value = result.items || []
    activeId.value = result.active_id || ''
  } catch (error) { showToast('模型配置加载失败：' + error.message) }
  finally { loading.value = false }
}

function closeForm() {
  creating.value = false
  editingId.value = ''
}

function startCreate() {
  Object.assign(form, emptyForm())
  editingId.value = ''
  creating.value = true
}

function startEdit(config) {
  Object.assign(form, {
    name: config.name,
    endpoint_url: config.endpoint_url,
    model_id: config.model_id,
    api_key: '',
    temperature: config.temperature,
    max_tokens: config.max_tokens,
    reasoning: config.reasoning,
    timeout_seconds: config.timeout_seconds,
    activate: false,
  })
  creating.value = false
  editingId.value = config.id
}

async function save() {
  if (saving.value) return
  if (!editingId.value && !form.api_key) {
    showToast('新建模型必须提供 API Key')
    return
  }
  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      endpoint_url: form.endpoint_url.trim(),
      model_id: form.model_id.trim(),
      temperature: Number(form.temperature),
      max_tokens: Number(form.max_tokens),
      reasoning: form.reasoning,
      timeout_seconds: Number(form.timeout_seconds),
    }
    if (form.api_key) body.api_key = form.api_key
    if (editingId.value) await api.updateModelConfig(editingId.value, body)
    else await api.createModelConfig({ ...body, activate: Boolean(form.activate) })
    showToast(editingId.value ? '模型配置已更新' : '模型配置已创建')
    closeForm()
    await reload()
  } catch (error) { showToast('保存失败：' + error.message) }
  finally { saving.value = false }
}

async function testConfig(config) {
  if (tests[config.id]?.pending) return
  tests[config.id] = { pending: true }
  try { tests[config.id] = await api.testModelConfig(config.id) }
  catch (error) { tests[config.id] = { ok: false, error: error.message } }
}

async function activate(config) {
  const key = `activate:${config.id}`
  if (actionPending[key]) return
  actionPending[key] = true
  try {
    await api.activateModelConfig(config.id)
    showToast(`已激活「${config.name}」，后续问答将使用该模型`)
    await reload()
  } catch (error) { showToast('激活失败：' + error.message) }
  finally { actionPending[key] = false }
}

async function remove(config) {
  const key = `delete:${config.id}`
  if (actionPending[key]) return
  const isActive = config.id === activeId.value
  const message = isActive
    ? `「${config.name}」当前已激活。删除后问答将无可用模型，直到重新创建并激活。确定删除？`
    : `删除模型配置「${config.name}」？该操作不可恢复。`
  if (!window.confirm(message)) return
  actionPending[key] = true
  try {
    await api.deleteModelConfig(config.id)
    showToast('模型配置已删除')
    if (editingId.value === config.id) closeForm()
    await reload()
  } catch (error) { showToast('删除失败：' + error.message) }
  finally { actionPending[key] = false }
}

onMounted(reload)
</script>

<template>
  <div class="page-shell wide-page">
    <div class="model-page">
      <header class="page-head">
        <div>
          <div class="eyebrow">模型</div>
          <h1>模型配置</h1>
          <p>Agent 循环使用当前激活的模型；API Key 加密存储在服务端，永不回显。</p>
        </div>
        <button class="btn-p" type="button" @click="creating ? closeForm() : startCreate()">{{ creating ? '关闭表单' : '＋ 新建模型' }}</button>
      </header>

      <section class="model-list">
        <form v-if="creating" class="panel model-editor" @submit.prevent="save">
          <div class="editor-head">
            <div><span>新建</span><h2>新建模型</h2></div>
            <span class="security-note">API Key 不会回显</span>
          </div>
          <div class="form-grid model-main-grid">
            <label class="field"><span>名称</span><input v-model="form.name" required maxlength="160" placeholder="DeepSeek Flash 生产" /></label>
            <label class="field"><span>模型 ID</span><input v-model="form.model_id" required maxlength="160" placeholder="deepseek-flash" /></label>
            <label class="field span-2"><span>接口地址（Base URL 或完整调用地址）</span><input v-model="form.endpoint_url" required placeholder="https://api.deepseek.com" /></label>
            <label class="field span-2"><span>API Key</span><input v-model="form.api_key" type="password" autocomplete="new-password" required placeholder="服务端加密存储" /></label>
          </div>
          <details class="model-advanced">
            <summary><span>调用参数</span><em>{{ paramSummary(form) }}</em></summary>
            <div class="model-advanced-grid">
              <label class="field"><span>Temperature</span><input v-model.number="form.temperature" type="number" step="0.1" min="0" max="2" /></label>
              <label class="field"><span>Max Tokens</span><input v-model.number="form.max_tokens" type="number" step="1024" min="2048" max="65536" /></label>
              <label class="field"><span>深度思考</span><select v-model="form.reasoning"><option value="auto">自动</option><option value="on">开启</option><option value="off">关闭</option></select></label>
              <label class="field"><span>超时（秒）</span><input v-model.number="form.timeout_seconds" type="number" min="1" max="300" /></label>
            </div>
          </details>
          <label class="check-field"><input v-model="form.activate" type="checkbox" /><span>创建后立即激活</span><small>激活后所有新问答将使用该模型。</small></label>
          <div class="form-actions">
            <button class="btn-p" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
            <button class="btn-g" type="button" @click="closeForm()">取消</button>
          </div>
        </form>

        <div v-if="loading" class="loading-state">加载中…</div>
        <div v-else-if="!configs.length && !creating" class="empty-state panel"><b>暂无模型配置</b><span>创建一个模型配置并激活后，Agent 才能开始工作。</span></div>

        <article
          v-for="config in configs"
          :key="config.id"
          class="panel"
          :class="editingId === config.id ? 'model-editor' : 'model-card'"
          :data-active="config.id === activeId ? 'true' : 'false'"
        >
          <form v-if="editingId === config.id" @submit.prevent="save">
            <div class="editor-head">
              <div><span>编辑</span><h2>{{ config.name }}</h2></div>
              <span class="security-note">API Key 不会回显</span>
            </div>
            <div class="form-grid model-main-grid">
              <label class="field"><span>名称</span><input v-model="form.name" required maxlength="160" /></label>
              <label class="field"><span>模型 ID</span><input v-model="form.model_id" required maxlength="160" /></label>
              <label class="field span-2"><span>接口地址（Base URL 或完整调用地址）</span><input v-model="form.endpoint_url" required /></label>
              <label class="field span-2"><span>API Key</span><input v-model="form.api_key" type="password" autocomplete="new-password" placeholder="留空表示不修改" /></label>
            </div>
            <details class="model-advanced">
              <summary><span>调用参数</span><em>{{ paramSummary(form) }}</em></summary>
              <div class="model-advanced-grid">
                <label class="field"><span>Temperature</span><input v-model.number="form.temperature" type="number" step="0.1" min="0" max="2" /></label>
                <label class="field"><span>Max Tokens</span><input v-model.number="form.max_tokens" type="number" step="1024" min="2048" max="65536" /></label>
                <label class="field"><span>深度思考</span><select v-model="form.reasoning"><option value="auto">自动</option><option value="on">开启</option><option value="off">关闭</option></select></label>
                <label class="field"><span>超时（秒）</span><input v-model.number="form.timeout_seconds" type="number" min="1" max="300" /></label>
              </div>
            </details>
            <div class="form-actions">
              <button class="btn-p" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
              <button class="btn-g" type="button" @click="closeForm()">取消</button>
            </div>
          </form>

          <template v-else>
            <header class="model-card-head">
              <div class="model-icon">模</div>
              <div class="model-title">
                <div>
                  <h2>{{ config.name }}</h2>
                  <span :class="['status-badge', config.id === activeId ? 'active' : 'disabled']">{{ config.id === activeId ? '已激活' : '未激活' }}</span>
                </div>
                <code>{{ config.model_id }} · {{ config.endpoint_url }}</code>
                <p>{{ paramSummary(config) }}</p>
              </div>
            </header>
            <div v-if="tests[config.id]" :class="['test-result', tests[config.id].pending ? 'pending' : tests[config.id].ok ? 'ok' : 'failed']">
              <template v-if="tests[config.id].pending">正在执行连通测试…</template>
              <template v-else-if="tests[config.id].ok"><b>✓ 测试通过</b><span>{{ tests[config.id].latency_ms }}ms · {{ tests[config.id].model_id }}</span><small v-if="tests[config.id].preview">回应：{{ tests[config.id].preview }}</small></template>
              <template v-else><b>测试失败</b><span>{{ tests[config.id].error || '未知错误' }}</span></template>
            </div>
            <footer class="model-actions">
              <button class="btn-g" :disabled="tests[config.id]?.pending" @click="testConfig(config)">{{ tests[config.id]?.pending ? '测试中…' : '测试连通' }}</button>
              <button class="btn-g" @click="startEdit(config)">编辑</button>
              <button v-if="config.id !== activeId" class="btn-p" :disabled="actionPending[`activate:${config.id}`]" @click="activate(config)">{{ actionPending[`activate:${config.id}`] ? '激活中…' : '激活' }}</button>
              <button class="btn-text danger" :disabled="actionPending[`delete:${config.id}`]" @click="remove(config)">{{ actionPending[`delete:${config.id}`] ? '删除中…' : '删除' }}</button>
              <span class="model-meta">更新于 {{ formatDate(config.updated_at) }}</span>
            </footer>
          </template>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.model-page { margin: 0 auto; max-width: 1120px; width: 100%; }
.model-page .page-head { margin-left: 0; margin-right: 0; max-width: none; }
.model-list { display: grid; gap: 14px; }
.model-card { display: grid; gap: 12px; padding: 16px 18px; }
.model-card[data-active='true'] { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent); }
.model-card-head { display: flex; gap: 12px; align-items: flex-start; }
.model-icon { align-items: center; background: var(--accent-soft); border-radius: 12px; color: var(--accent-dark); display: flex; flex: 0 0 40px; font-size: 13px; font-weight: 700; height: 40px; justify-content: center; }
.model-title { min-width: 0; }
.model-title > div { align-items: center; display: flex; gap: 8px; }
.model-title h2 { font-size: 15px; margin: 0; }
.model-title code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-title p { color: var(--ink-3); font-size: 12px; margin-top: 4px; }
.model-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.model-meta { color: var(--ink-3); font-size: 11px; margin-left: auto; }
.model-editor { padding: 18px 20px 16px; }
.editor-head { align-items: center; display: flex; justify-content: space-between; margin-bottom: 16px; }
.editor-head span { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.editor-head h2 { font-size: 17px; font-weight: 650; letter-spacing: -.02em; margin-top: 2px; }
.model-main-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.model-advanced { margin-top: 14px; }
.model-advanced summary {
  align-items: baseline;
  color: var(--ink-2);
  cursor: pointer;
  display: flex;
  gap: 10px;
  font-size: 12px;
  font-weight: 650;
  list-style: none;
}
.model-advanced summary::-webkit-details-marker { display: none; }
.model-advanced summary::before { color: var(--ink-3); content: '▸'; font-size: 11px; }
.model-advanced[open] summary::before { content: '▾'; }
.model-advanced summary em { color: var(--ink-3); font-style: normal; font-weight: 400; }
.model-advanced-grid { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 12px; }
.model-editor :deep(.form-actions) { margin-top: 14px; }
.model-editor :deep(.check-field) { margin-top: 12px; }
@media (max-width: 760px) {
  .model-main-grid, .model-advanced-grid { grid-template-columns: 1fr; }
}
</style>
