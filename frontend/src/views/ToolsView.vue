<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { showToast } from '../store.js'

const items = ref([])
const openName = ref('')
const configOpen = ref(false)
const probing = ref(false)
const saving = ref(false)
const credentialConfigured = ref(false)
const tables = ref([])
const form = reactive(emptyForm())
const current = computed(() => items.value.find(item => item.name === openName.value) || null)
const selectedCount = computed(() => tables.value.filter(item => item.selected).length)

function emptyForm() {
  return {
    source_id: '',
    name: '智能体查询库',
    connection_url: '',
    username: '',
    password: '',
    selected_database: '',
    schema: '',
    dialect: 'mysql',
    ssl_mode: 'disable',
    query_timeout_seconds: 15,
    max_rows: 2000,
    allow_private_network: true,
  }
}

function open(name) {
  openName.value = name
}

function close() {
  openName.value = ''
}

function onDialectChange() {
  if (form.dialect === 'sqlite') form.ssl_mode = 'disable'
}

function probeBody() {
  const body = {
    name: form.name.trim() || '智能体查询库',
    connection_url: form.connection_url.trim(),
    username: form.username.trim() || null,
    selected_database: form.selected_database.trim(),
    schema: form.schema.trim() || null,
    dialect: form.dialect,
    ssl_mode: form.dialect === 'sqlite' ? 'disable' : form.ssl_mode,
    allow_private_network: Boolean(form.allow_private_network),
    query_timeout_seconds: Number(form.query_timeout_seconds) || 15,
    max_rows: Number(form.max_rows) || 2000,
    allowed_objects: tables.value.filter(item => item.selected).map(item => item.name),
  }
  if (form.source_id) body.source_id = form.source_id
  if (form.password) body.password = form.password
  return body
}

async function openConfig(tool) {
  openName.value = ''
  if (!tool.configurable) return
  configOpen.value = true
  tables.value = []
  Object.assign(form, emptyForm())
  try {
    const result = await api.queryToolConfig()
    const next = result.form || {}
    Object.assign(form, {
      ...emptyForm(),
      ...next,
      password: '',
    })
    credentialConfigured.value = Boolean(result.source?.credential_configured)
    const selected = new Set(result.selected || [])
    tables.value = (result.tables || []).map(name => ({
      name,
      selected: selected.size ? selected.has(name) : true,
      columns: result.columns?.[name] || [],
    }))
  } catch (error) {
    showToast('加载连接配置失败：' + error.message)
  }
}

function closeConfig() {
  configOpen.value = false
}

async function loadTables() {
  if (probing.value) return
  if (!form.connection_url.trim() || !form.selected_database.trim()) {
    showToast('请先填写连接地址和数据库名')
    return
  }
  if (form.dialect !== 'sqlite' && !form.password && !credentialConfigured.value) {
    showToast('请填写数据库密码')
    return
  }
  probing.value = true
  try {
    const result = await api.probeQueryTool(probeBody())
    if (!result.ok) {
      showToast(result.errors?.join('；') || '连接失败')
      return
    }
    const keep = new Set(tables.value.filter(item => item.selected).map(item => item.name))
    const hadSelection = tables.value.some(item => item.selected)
    tables.value = (result.tables || []).map(name => ({
      name,
      selected: hadSelection ? keep.has(name) : true,
      columns: result.columns?.[name] || [],
    }))
    showToast(`已加载 ${tables.value.length} 张表，勾选后保存`)
  } catch (error) {
    showToast('加载表失败：' + error.message)
  } finally {
    probing.value = false
  }
}

function toggleAll(on) {
  tables.value.forEach(item => { item.selected = on })
}

async function saveConfig() {
  if (saving.value) return
  const selected = tables.value.filter(item => item.selected).map(item => item.name)
  if (!selected.length) {
    showToast('请至少勾选一张表')
    return
  }
  saving.value = true
  try {
    await api.saveQueryToolConfig({ ...probeBody(), allowed_objects: selected })
    showToast('数据库连接已保存')
    closeConfig()
  } catch (error) {
    showToast('保存失败：' + error.message)
  } finally {
    saving.value = false
  }
}

function icon(label) {
  return [...label].find(char => /[\u4e00-\u9fff]/.test(char)) || label.slice(0, 1)
}

function onKey(event) {
  if (event.key !== 'Escape') return
  if (configOpen.value) {
    closeConfig()
    return
  }
  close()
}

async function reload() {
  try {
    const result = await api.tools()
    items.value = result.items || []
  } catch (error) {
    showToast('工具目录加载失败：' + error.message)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  reload()
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="page-shell fill-page">
    <header class="page-head">
      <div>
        <div class="eyebrow">管理</div>
        <h1>工具目录</h1>
        <p>管理查询工具和实验室连接。要改谁能用，去智能体页勾选。</p>
      </div>
      <span class="count-chip">{{ items.length }} 个已注册</span>
    </header>

    <router-link class="panel connection-entry" to="/lab-connection">
      <span class="tool-icon">连</span>
      <span><strong>实验室连接</strong><small>选择 Bootcamp 或百炼，配置连接并测试；也可以开启演示数据。</small></span>
      <span class="connection-cta">去配置 <span aria-hidden="true">→</span></span>
    </router-link>

    <section class="card-grid">
      <article
        v-for="tool in items"
        :key="tool.name"
        class="panel tool-card"
        role="button"
        tabindex="0"
        @click="tool.configurable ? openConfig(tool) : open(tool.name)"
        @keydown.enter.prevent="tool.configurable ? openConfig(tool) : open(tool.name)"
      >
        <div class="tool-icon">{{ icon(tool.label) }}</div>
        <div class="tool-title">
          <div>
            <h2>{{ tool.label }}</h2>
            <span class="status-badge">{{ tool.configurable ? '可配置' : '代码注册' }}</span>
          </div>
          <code>{{ tool.name }}</code>
        </div>
        <div class="chip-row">
          <span v-for="agent in tool.usedBy" :key="agent.id" class="mini-chip">{{ agent.name }}</span>
          <span v-if="!tool.usedBy.length" class="mini-empty">暂无智能体使用</span>
        </div>
        <span class="tool-more">{{ tool.configurable ? '点击配置' : '查看说明' }}</span>
      </article>
    </section>

    <div v-if="current" class="veil" @click.self="close">
      <div class="detail-modal" role="dialog" aria-modal="true">
        <header class="detail-head">
          <div class="tool-icon">{{ icon(current.label) }}</div>
          <div>
            <div>
              <h2>{{ current.label }}</h2>
              <span class="status-badge">代码注册</span>
            </div>
            <code>{{ current.name }}</code>
          </div>
        </header>
        <p class="detail-copy">{{ current.description }}</p>
        <section class="detail-block">
          <h3>参数 · 只读</h3>
          <ul>
            <li v-for="param in current.parameters" :key="param.name">
              <code>{{ param.name }}</code>
              <em v-if="param.required">必填</em>
              <em v-else>可选</em>
              {{ param.text }}
            </li>
          </ul>
        </section>
        <section class="detail-block">
          <h3>被哪些智能体使用</h3>
          <p v-if="!current.usedBy.length" class="empty-inline">当前没有智能体勾选此工具。</p>
          <div v-else class="used-row">
            <span v-for="agent in current.usedBy" :key="agent.id" class="used-chip">{{ agent.name }}</span>
          </div>
        </section>
        <footer class="detail-actions">
          <button v-if="current.configurable" class="btn-g" type="button" @click="openConfig(current)">配置连接</button>
          <button class="btn-p" type="button" @click="close">关闭</button>
        </footer>
      </div>
    </div>

    <div v-if="configOpen" class="veil" @click.self="closeConfig">
      <div class="config-modal" role="dialog" aria-modal="true">
        <header class="detail-head">
          <div class="tool-icon">库</div>
          <div>
            <div>
              <h2>数据库查询</h2>
              <span class="status-badge">本地连接</span>
            </div>
            <code>query_db</code>
          </div>
        </header>
        <p class="detail-copy">配置百炼模式使用的查询数据库。Bootcamp 模式使用平台数据，演示模式使用预置数据。</p>
        <form class="config-form" @submit.prevent="saveConfig">
          <div class="form-grid">
            <label class="field"><span>名称</span><input v-model="form.name" maxlength="160" /></label>
            <label class="field"><span>数据库类型</span>
              <select v-model="form.dialect" @change="onDialectChange">
                <option value="mysql">MySQL</option>
                <option value="postgresql">PostgreSQL</option>
                <option value="sqlite">SQLite</option>
              </select>
            </label>
            <label class="field span-2"><span>连接地址</span><input v-model="form.connection_url" required placeholder="mysql+pymysql://127.0.0.1:3306" /></label>
            <label class="field"><span>账号</span><input v-model="form.username" autocomplete="off" placeholder="只读账号" /></label>
            <label class="field"><span>密码</span><input v-model="form.password" type="password" autocomplete="new-password" :placeholder="credentialConfigured ? '留空表示不修改' : '数据库密码'" /></label>
            <label class="field"><span>数据库</span><input v-model="form.selected_database" required placeholder="analytics" /></label>
            <label class="field"><span>Schema</span><input v-model="form.schema" placeholder="可空" /></label>
            <label class="check-field span-2"><input v-model="form.allow_private_network" type="checkbox" /><span>允许内网 / 本机地址</span></label>
          </div>
          <div class="table-toolbar">
            <button class="btn-g" type="button" :disabled="probing" @click="loadTables">{{ probing ? '加载中…' : '加载所有表' }}</button>
            <span v-if="tables.length">已选 {{ selectedCount }} / {{ tables.length }}</span>
            <button v-if="tables.length" class="btn-text" type="button" @click="toggleAll(true)">全选</button>
            <button v-if="tables.length" class="btn-text" type="button" @click="toggleAll(false)">清空</button>
          </div>
          <div v-if="tables.length" class="table-list">
            <label v-for="table in tables" :key="table.name" class="table-row">
              <input v-model="table.selected" type="checkbox" />
              <div>
                <b>{{ table.name }}</b>
                <small v-if="table.columns.length">{{ table.columns.slice(0, 8).join(' · ') }}<template v-if="table.columns.length > 8"> …</template></small>
              </div>
            </label>
          </div>
          <p v-else class="empty-inline">填好连接后点「加载所有表」，再勾选查询和召回要用的表。</p>
          <footer class="detail-actions">
            <button class="btn-g" type="button" @click="closeConfig">取消</button>
            <button class="btn-p" :disabled="saving">{{ saving ? '保存中…' : '保存并启用' }}</button>
          </footer>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fill-page { padding: 28px 28px 48px; }
.fill-page .page-head { margin: 0 0 22px; max-width: none; }
.connection-entry { align-items: center; display: flex; gap: 14px; margin-bottom: 20px; padding: 18px 20px; text-decoration: none; transition: border-color .15s; }
.connection-entry:hover { border-color: var(--accent); }
.connection-entry .tool-icon { flex: 0 0 40px; }
.connection-entry strong { color: var(--ink); display: block; font-size: 15px; }
.connection-entry small { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.connection-cta { flex-shrink: 0; font-size: 12px; font-weight: 650; margin-left: auto; }
.card-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.tool-card {
  cursor: pointer;
  display: grid;
  gap: 12px;
  grid-template-columns: 40px 1fr;
  min-height: 148px;
  padding: 16px 18px;
  transition: border-color .15s, transform .15s;
}
.tool-card:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
  transform: translateY(-1px);
}
.tool-icon {
  align-items: center;
  background: var(--accent-soft);
  border-radius: 12px;
  color: var(--accent-dark);
  display: flex;
  font-size: 13px;
  font-weight: 700;
  height: 40px;
  justify-content: center;
  width: 40px;
}
.tool-title { min-width: 0; }
.tool-title > div { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.tool-title h2 { font-size: 15px; margin: 0; }
.tool-title code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; grid-column: 1 / -1; }
.mini-chip {
  background: var(--accent-soft);
  border-radius: 999px;
  color: var(--accent-dark);
  font-size: 11px;
  font-weight: 650;
  padding: 3px 8px;
}
.mini-empty { color: var(--ink-3); font-size: 12px; }
.tool-more {
  color: var(--accent);
  font-size: 11px;
  font-weight: 650;
  grid-column: 1 / -1;
  margin-top: auto;
}

.detail-modal {
  background: var(--paper);
  border-radius: 22px;
  box-shadow: var(--shadow-lg);
  max-height: min(86vh, 720px);
  overflow: auto;
  padding: 22px 24px 18px;
  text-align: left;
  width: min(560px, 100%);
}
.detail-head { align-items: flex-start; display: flex; gap: 12px; margin-bottom: 12px; }
.detail-head > div > div { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.detail-head h2 { font-size: 20px; font-weight: 650; letter-spacing: -.02em; }
.detail-head code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.detail-copy { color: var(--ink-2); font-size: 13px; line-height: 1.65; margin-bottom: 16px; }
.detail-block + .detail-block { margin-top: 16px; }
.detail-block h3 { color: var(--ink-3); font-size: 11px; font-weight: 650; margin-bottom: 8px; }
.detail-block ul { list-style: none; }
.detail-block li {
  color: var(--ink-2);
  font-size: 12.5px;
  line-height: 1.6;
  padding: 7px 0;
}
.detail-block li + li { border-top: 1px dashed var(--line); }
.detail-block code { color: var(--accent); font-size: 12px; margin-right: 8px; }
.detail-block em {
  background: #eeeae6;
  border-radius: 999px;
  color: var(--ink-3);
  font-size: 10px;
  font-style: normal;
  font-weight: 650;
  margin-right: 8px;
  padding: 1px 6px;
}
.used-row { display: flex; flex-wrap: wrap; gap: 6px; }
.used-chip {
  background: var(--accent-soft);
  border-radius: 999px;
  color: var(--accent-dark);
  font-size: 11px;
  font-weight: 650;
  padding: 3px 8px;
}
.detail-actions {
  border-top: 1px solid var(--line);
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 14px;
}
.config-modal {
  background: var(--paper);
  border-radius: 22px;
  box-shadow: var(--shadow-lg);
  max-height: min(90vh, 860px);
  overflow: auto;
  padding: 22px 24px 18px;
  text-align: left;
  width: min(720px, 100%);
}
.table-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 16px 0 10px;
}
.table-toolbar span { color: var(--ink-3); font-size: 12px; }
.table-list {
  border: 1px solid var(--line);
  border-radius: 14px;
  display: grid;
  gap: 0;
  max-height: 280px;
  overflow: auto;
}
.table-row {
  align-items: flex-start;
  display: grid;
  gap: 10px;
  grid-template-columns: auto 1fr;
  padding: 10px 12px;
}
.table-row + .table-row { border-top: 1px dashed var(--line); }
.table-row b { display: block; font-size: 13px; }
.table-row small { color: var(--ink-3); display: block; font-size: 11px; margin-top: 2px; }
.empty-inline { color: var(--ink-3); font-size: 12.5px; }
@media (max-width: 760px) {
  .fill-page { padding: 20px 16px 40px; }
  .connection-entry { flex-wrap: wrap; padding: 16px; }
}
</style>
