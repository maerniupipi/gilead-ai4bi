<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, showToast } from '../store.js'

const sources = ref([])
const documents = ref([])
const tests = reactive({})
const actionPending = reactive({})
const creating = ref(false)
const editingId = ref('')
const saving = ref(false)
const labSourceId = ref('')
const labLockedName = ref('')
const labSaving = ref(false)
const form = reactive(emptyForm())
const labForm = reactive({ name: '', customName: '', token: '' })

function emptyForm() {
  return {
    name: '', connection_url: '', username: '', password: '', selected_database: '', schema: '',
    dialect: 'postgresql', ssl_mode: 'require', query_timeout_seconds: 15, max_rows: 2000,
    allow_private_network: false, allowed_objects: [], allowed_schemas: [],
  }
}

const selectedDocument = computed(() => {
  const name = labForm.name === 'custom' ? labForm.customName : labForm.name
  return documents.value.find(item => item.name === name || item.lab_id === name) || null
})

function dialectLabel(dialect) {
  return { postgresql: 'PG', mysql: 'MY', sqlite: 'SQ' }[dialect] || '库'
}

function stateLabel(state) {
  return { active: '已启用', disabled: '已停用', draft: '待启用' }[state] || state
}

function availableDocuments(source) {
  const used = new Set((source.labs || []).map(item => item.lab_id))
  return documents.value.filter(item => !used.has(item.lab_id))
}

function bodyFromForm() {
  return {
    name: form.name.trim(),
    connection_url: form.connection_url.trim(),
    ...(form.username.trim() ? { username: form.username.trim() } : { username: null }),
    ...(form.password ? { password: form.password } : {}),
    selected_database: form.selected_database.trim(),
    ...(form.schema.trim() ? { schema: form.schema.trim() } : { schema: null }),
    dialect: form.dialect,
    ssl_mode: form.dialect === 'sqlite' ? 'disable' : form.ssl_mode,
    allowed_objects: form.allowed_objects,
    allowed_schemas: form.allowed_schemas,
    query_timeout_seconds: Number(form.query_timeout_seconds),
    max_rows: Number(form.max_rows),
    allow_private_network: Boolean(form.allow_private_network),
  }
}

async function reload() {
  try {
    const [sourceItems, documentItems] = await Promise.all([api.dataSources(), api.labDocuments()])
    sources.value = sourceItems
    documents.value = documentItems
  } catch (error) { showToast('数据源加载失败：' + error.message) }
}

function closeForm() {
  creating.value = false
  editingId.value = ''
}

function closeLabForm() {
  labSourceId.value = ''
  labLockedName.value = ''
  Object.assign(labForm, { name: '', customName: '', token: '' })
}

function startCreate() {
  Object.assign(form, emptyForm())
  editingId.value = ''
  creating.value = true
  closeLabForm()
}

function startEdit(source) {
  Object.assign(form, {
    name: source.name,
    connection_url: source.connection_url,
    username: source.username || '',
    password: '',
    selected_database: source.selected_database,
    schema: source.schema || '',
    dialect: source.dialect,
    ssl_mode: source.ssl_mode || 'disable',
    query_timeout_seconds: source.query_timeout_seconds,
    max_rows: source.max_rows,
    allow_private_network: source.allow_private_network,
    allowed_objects: source.allowed_objects || [],
    allowed_schemas: source.allowed_schemas || [],
  })
  creating.value = false
  editingId.value = source.id
  closeLabForm()
}

function onDialectChange() {
  if (form.dialect === 'sqlite') form.ssl_mode = 'disable'
}

async function save() {
  if (saving.value) return
  if (!editingId.value && form.dialect !== 'sqlite' && !form.password) {
    showToast('非 SQLite 数据源必须配置密码')
    return
  }
  saving.value = true
  try {
    if (editingId.value) await api.updateDataSource(editingId.value, bodyFromForm())
    else await api.createDataSource(bodyFromForm())
    showToast(editingId.value ? '数据源已更新' : '数据源已创建')
    closeForm()
    await reload()
  } catch (error) { showToast('保存失败：' + error.message) }
  finally { saving.value = false }
}

async function testSource(source) {
  if (tests[source.id]?.pending) return
  tests[source.id] = { pending: true }
  try { tests[source.id] = await api.testDataSource(source.id) }
  catch (error) { tests[source.id] = { ok: false, errors: [error.message] } }
}

async function enable(source) {
  const key = `enable:${source.id}`
  if (actionPending[key]) return
  actionPending[key] = true
  try {
    await api.activateDataSource(source.id)
    showToast(`已启用「${source.name}」`)
    await reload()
  } catch (error) { showToast('启用失败：' + error.message) }
  finally { actionPending[key] = false }
}

async function disable(source) {
  const key = `disable:${source.id}`
  if (actionPending[key]) return
  if (!window.confirm(`停用数据源“${source.name}”？实验室绑定会暂停，配置还在。`)) return
  actionPending[key] = true
  try { await api.disableDataSource(source.id); showToast('数据源已停用'); await reload() }
  catch (error) { showToast('停用失败：' + error.message) }
  finally { actionPending[key] = false }
}

function startAddLab(source) {
  closeForm()
  labSourceId.value = source.id
  labLockedName.value = ''
  const first = availableDocuments(source)[0]
  Object.assign(labForm, { name: first?.name || 'custom', customName: '', token: '' })
}

function startRotateLab(source, lab) {
  closeForm()
  labSourceId.value = source.id
  labLockedName.value = lab.name
  Object.assign(labForm, { name: lab.name, customName: '', token: '' })
}

async function saveLab() {
  if (labSaving.value || !labSourceId.value) return
  const name = labLockedName.value || (labForm.name === 'custom' ? labForm.customName.trim() : labForm.name)
  if (!name || !labForm.token) {
    showToast('请填写实验室名称和 Token')
    return
  }
  labSaving.value = true
  try {
    await api.attachLab(labSourceId.value, { name, token: labForm.token })
    showToast(labLockedName.value ? 'Token 已更新' : `已添加「${name}」`)
    closeLabForm()
    await reload()
  } catch (error) { showToast('保存实验室失败：' + error.message) }
  finally { labSaving.value = false }
}

async function removeLab(source, lab) {
  const key = `lab:${lab.lab_id}`
  if (actionPending[key]) return
  if (!window.confirm(`从「${source.name}」移除实验室“${lab.name}”？`)) return
  actionPending[key] = true
  try {
    await api.detachLab(source.id, lab.lab_id)
    showToast(`已移除「${lab.name}」`)
    await reload()
  } catch (error) { showToast('移除失败：' + error.message) }
  finally { actionPending[key] = false }
}

onMounted(reload)
</script>

<template>
  <div class="page-shell wide-page">
    <div class="source-page">
      <header class="page-head">
        <div>
          <div class="eyebrow">管理</div>
          <h1>数据源</h1>
          <p>先接上数据库，再给实验室一个名称和 Token。白名单、超时、连接都沿用本库。</p>
        </div>
        <button class="btn-p" type="button" @click="creating ? closeForm() : startCreate()">{{ creating ? '关闭表单' : '＋ 新建数据源' }}</button>
      </header>

      <section class="source-list">
        <form v-if="creating" class="panel source-editor" @submit.prevent="save">
          <div class="editor-head">
            <div><span>连接</span><h2>新建数据源</h2></div>
            <span class="security-note">密码不会回显</span>
          </div>
          <div class="form-grid source-main-grid">
            <label class="field"><span>名称</span><input v-model="form.name" required maxlength="160" placeholder="销售分析库" /></label>
            <label class="field"><span>数据库类型</span>
              <select v-model="form.dialect" @change="onDialectChange">
                <option value="postgresql">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="sqlite">SQLite</option>
              </select>
            </label>
            <label class="field span-2"><span>连接地址</span><input v-model="form.connection_url" required placeholder="postgresql://db.internal:5432" /></label>
            <label class="field"><span>账号</span><input v-model="form.username" autocomplete="off" placeholder="只读账号" /></label>
            <label class="field"><span>密码</span><input v-model="form.password" type="password" autocomplete="new-password" placeholder="数据库密码" /></label>
            <label class="field"><span>数据库</span><input v-model="form.selected_database" required placeholder="analytics" /></label>
            <label class="field"><span>Schema</span><input v-model="form.schema" placeholder="public" /></label>
          </div>
          <details class="source-advanced">
            <summary><span>限额与安全</span><em>有默认值，一般不用改</em></summary>
            <div class="source-advanced-grid">
              <label class="field"><span>TLS</span>
                <select v-model="form.ssl_mode" :disabled="form.dialect === 'sqlite'">
                  <option value="disable">disable</option>
                  <option value="prefer">prefer</option>
                  <option value="require">require</option>
                  <option value="verify_ca">verify_ca</option>
                  <option value="verify_full">verify_full</option>
                </select>
              </label>
              <label class="field"><span>查询超时（秒）</span><input v-model.number="form.query_timeout_seconds" type="number" min="1" max="120" /></label>
              <label class="field"><span>最大返回行数</span><input v-model.number="form.max_rows" type="number" min="1" max="10000" /></label>
              <label class="check-field tight"><input v-model="form.allow_private_network" type="checkbox" /><span>允许内网</span></label>
            </div>
          </details>
          <div class="form-actions">
            <button class="btn-p" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
            <button class="btn-g" type="button" @click="closeForm()">取消</button>
          </div>
        </form>

        <div v-if="!sources.length && !creating" class="empty-state panel"><b>暂无数据源</b><span>先创建连接，再给实验室名称和 Token。</span></div>

        <article
          v-for="source in sources"
          :key="source.id"
          class="panel"
          :class="editingId === source.id ? 'source-editor' : 'source-card'"
          :data-active="source.state === 'active' ? 'true' : 'false'"
        >
          <form v-if="editingId === source.id" @submit.prevent="save">
            <div class="editor-head">
              <div><span>编辑</span><h2>{{ source.name }}</h2></div>
              <span class="security-note">密码不会回显</span>
            </div>
            <div class="form-grid source-main-grid">
              <label class="field"><span>名称</span><input v-model="form.name" required maxlength="160" /></label>
              <label class="field"><span>数据库类型</span>
                <select v-model="form.dialect" @change="onDialectChange">
                  <option value="postgresql">PostgreSQL</option>
                  <option value="mysql">MySQL</option>
                  <option value="sqlite">SQLite</option>
                </select>
              </label>
              <label class="field span-2"><span>连接地址</span><input v-model="form.connection_url" required /></label>
              <label class="field"><span>账号</span><input v-model="form.username" autocomplete="off" /></label>
              <label class="field"><span>密码</span><input v-model="form.password" type="password" autocomplete="new-password" placeholder="留空表示不修改" /></label>
              <label class="field"><span>数据库</span><input v-model="form.selected_database" required /></label>
              <label class="field"><span>Schema</span><input v-model="form.schema" /></label>
            </div>
            <details class="source-advanced">
              <summary><span>限额与安全</span><em>{{ form.query_timeout_seconds }}s · {{ form.max_rows }} 行 · TLS {{ form.ssl_mode }}</em></summary>
              <div class="source-advanced-grid">
                <label class="field"><span>TLS</span>
                  <select v-model="form.ssl_mode" :disabled="form.dialect === 'sqlite'">
                    <option value="disable">disable</option>
                    <option value="prefer">prefer</option>
                    <option value="require">require</option>
                    <option value="verify_ca">verify_ca</option>
                    <option value="verify_full">verify_full</option>
                  </select>
                </label>
                <label class="field"><span>查询超时（秒）</span><input v-model.number="form.query_timeout_seconds" type="number" min="1" max="120" /></label>
                <label class="field"><span>最大返回行数</span><input v-model.number="form.max_rows" type="number" min="1" max="10000" /></label>
                <label class="check-field tight"><input v-model="form.allow_private_network" type="checkbox" /><span>允许内网</span></label>
              </div>
            </details>
            <div class="form-actions">
              <button class="btn-p" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
              <button class="btn-g" type="button" @click="closeForm()">取消</button>
            </div>
          </form>

          <template v-else>
            <header class="source-card-head">
              <div class="db-icon">{{ dialectLabel(source.dialect) }}</div>
              <div class="source-title">
                <div>
                  <h2>{{ source.name }}</h2>
                  <span :class="['status-badge', source.state === 'active' ? 'active' : source.state === 'draft' ? 'pending' : 'disabled']">{{ stateLabel(source.state) }}</span>
                </div>
                <code>{{ source.dialect }} · {{ source.selected_database }}<template v-if="source.schema"> · {{ source.schema }}</template></code>
              </div>
            </header>

            <div class="labs-block">
              <div class="labs-head">
                <span>实验室 · 名称对应 labs/*.md</span>
                <button class="btn-text" type="button" @click="startAddLab(source)">＋ 添加实验室</button>
              </div>
              <div v-for="lab in source.labs" :key="lab.id" class="lab-row">
                <div>
                  <b>{{ lab.name }}</b>
                  <small :class="lab.document ? 'md-hit' : 'md-miss'">
                    <template v-if="lab.document">已匹配 {{ lab.document }}<template v-if="lab.blurb"> · {{ lab.blurb }}</template></template>
                    <template v-else>未找到对应文档</template>
                  </small>
                </div>
                <span :class="['token-chip', lab.token_configured ? 'ok' : 'miss']">{{ lab.token_configured ? 'Token 已配置' : '未配置 Token' }}</span>
                <button class="btn-text" type="button" @click="startRotateLab(source, lab)">更换</button>
                <button class="btn-text danger" type="button" :disabled="actionPending[`lab:${lab.lab_id}`]" @click="removeLab(source, lab)">移除</button>
              </div>
              <form v-if="labSourceId === source.id" class="lab-form" @submit.prevent="saveLab">
                <h3>{{ labLockedName ? '更换 Token' : `添加到「${source.name}」` }}</h3>
                <div class="form-grid lab-grid">
                  <label v-if="!labLockedName" class="field"><span>名称</span>
                    <select v-model="labForm.name">
                      <option v-for="doc in availableDocuments(source)" :key="doc.lab_id" :value="doc.name">{{ doc.name }}</option>
                      <option value="custom">自定义…</option>
                    </select>
                  </label>
                  <label v-if="!labLockedName && labForm.name === 'custom'" class="field"><span>自定义名称</span><input v-model="labForm.customName" placeholder="与 md 标题或文件名一致" /></label>
                  <label class="field span-2"><span>Token</span><input v-model="labForm.token" type="password" autocomplete="new-password" :placeholder="labLockedName ? '输入新 Token' : '实验室调用凭证，保存后不回显'" /></label>
                </div>
                <div v-if="selectedDocument" class="md-preview">
                  <b>{{ selectedDocument.name }}</b>
                  对应 <code>{{ selectedDocument.path }}</code><template v-if="selectedDocument.blurb"> · {{ selectedDocument.blurb }}</template>。连接、白名单、超时沿用本库。
                </div>
                <div v-else-if="labForm.name === 'custom'" class="md-preview miss">
                  <b>{{ labForm.customName.trim() || '自定义实验室' }}</b>
                  名称需与 <code>labs/</code> 下文档的标题或文件名对应。
                </div>
                <div class="form-actions lab-actions">
                  <button class="btn-p" :disabled="labSaving">{{ labSaving ? '保存中…' : '保存' }}</button>
                  <button class="btn-g" type="button" @click="closeLabForm()">取消</button>
                </div>
              </form>
            </div>

            <div v-if="tests[source.id]" :class="['test-result', tests[source.id].pending ? 'pending' : tests[source.id].ok ? 'ok' : 'failed']">
              <template v-if="tests[source.id].pending">正在执行只读连接测试…</template>
              <template v-else-if="tests[source.id].ok"><b>✓ 测试通过</b><span>{{ tests[source.id].latency_ms }}ms · {{ tests[source.id].server_version || 'server' }}</span></template>
              <template v-else><b>连接失败</b><span>{{ tests[source.id].errors?.join('；') || '未知错误' }}</span></template>
            </div>
            <footer class="source-actions">
              <button class="btn-g" :disabled="tests[source.id]?.pending" @click="testSource(source)">{{ tests[source.id]?.pending ? '测试中…' : '测试连接' }}</button>
              <button class="btn-g" @click="startEdit(source)">编辑</button>
              <button v-if="source.state !== 'active'" class="btn-p" :disabled="actionPending[`enable:${source.id}`]" @click="enable(source)">{{ actionPending[`enable:${source.id}`] ? '启用中…' : '启用' }}</button>
              <button v-else class="btn-text danger" :disabled="actionPending[`disable:${source.id}`]" @click="disable(source)">停用</button>
              <span class="source-meta">更新于 {{ formatDate(source.updated_at) }}</span>
            </footer>
          </template>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.source-page { margin: 0 auto; max-width: 1120px; width: 100%; }
.source-page .page-head { margin-left: 0; margin-right: 0; max-width: none; }
.source-list { display: grid; gap: 14px; }
.source-card { overflow: hidden; padding: 0; }
.source-card[data-active='true'] { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent); }
.source-card-head { display: flex; gap: 12px; align-items: flex-start; padding: 16px 18px 12px; }
.db-icon { align-items: center; background: var(--accent-soft); border-radius: 12px; color: var(--accent-dark); display: flex; flex: 0 0 40px; font-size: 12px; font-weight: 700; height: 40px; justify-content: center; }
.source-title { min-width: 0; }
.source-title > div { align-items: center; display: flex; gap: 8px; }
.source-title h2 { font-size: 15px; margin: 0; }
.source-title code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.source-editor { padding: 18px 20px 16px; }
.editor-head { align-items: center; display: flex; justify-content: space-between; margin-bottom: 16px; }
.editor-head span { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.editor-head h2 { font-size: 17px; font-weight: 650; letter-spacing: -.02em; margin-top: 2px; }
.source-main-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.source-advanced { margin-top: 14px; }
.source-advanced summary {
  align-items: baseline; color: var(--ink-2); cursor: pointer; display: flex; gap: 10px;
  font-size: 12px; font-weight: 650; list-style: none;
}
.source-advanced summary::-webkit-details-marker { display: none; }
.source-advanced summary::before { color: var(--ink-3); content: '▸'; font-size: 11px; }
.source-advanced[open] summary::before { content: '▾'; }
.source-advanced summary em { color: var(--ink-3); font-style: normal; font-weight: 400; }
.source-advanced-grid { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 12px; }
.labs-block { background: #faf7f8; border-top: 1px solid var(--line); padding: 10px 12px 12px; }
.labs-head { align-items: center; color: var(--ink-3); display: flex; font-size: 11px; font-weight: 650; justify-content: space-between; padding: 2px 6px 8px; }
.lab-row {
  align-items: center; background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
  display: grid; gap: 10px; grid-template-columns: 1fr auto auto auto; margin-top: 6px; padding: 10px 12px;
}
.lab-row b { display: block; font-size: 13px; font-weight: 650; }
.lab-row small { display: block; font-size: 11px; }
.md-hit { color: var(--success); }
.md-miss { color: var(--warning); }
.token-chip { background: #ece9e7; border-radius: 999px; color: var(--ink-3); font-size: 11px; font-weight: 650; padding: 4px 8px; }
.token-chip.ok { background: #e3f1eb; color: var(--success); }
.lab-form { background: var(--paper); border: 1px dashed color-mix(in srgb, var(--accent) 35%, var(--line)); border-radius: 14px; margin-top: 8px; padding: 14px; }
.lab-form h3 { font-size: 14px; font-weight: 650; margin-bottom: 10px; }
.lab-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.md-preview { background: #f6f1f3; border-left: 3px solid var(--accent); border-radius: 10px; color: var(--ink-2); font-size: 12px; margin: 10px 0 4px; padding: 8px 10px; }
.md-preview b { color: var(--ink); display: block; font-size: 12px; margin-bottom: 2px; }
.md-preview code { color: var(--accent); font-size: 11px; }
.md-preview.miss { background: #fbf2e2; border-left-color: var(--warning); }
.lab-actions { border: 0; margin-top: 10px; padding-top: 0; }
.source-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 18px 16px; }
.source-meta { color: var(--ink-3); font-size: 11px; margin-left: auto; }
.check-field.tight { margin-top: 18px; }
@media (max-width: 760px) {
  .source-main-grid, .source-advanced-grid, .lab-grid { grid-template-columns: 1fr; }
  .lab-row { grid-template-columns: 1fr auto; }
}
</style>
