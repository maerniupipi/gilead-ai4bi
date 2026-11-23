<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, showToast } from '../store.js'

const ROLE_LABEL = {
  admin: '管理员',
  knowledge_reviewer: '知识审核员',
  data_source_admin: '数据源管理员',
  user: '业务用户',
}
const SCOPE_LABEL = {
  all: '全部数据',
  deny: '拒绝访问',
  restricted: '按组织/区域',
}

const users = ref([])
const loading = ref(true)
const saving = ref(false)
const creating = ref(false)
const form = reactive(emptyForm())

function emptyForm() {
  return {
    username: '',
    password: '',
    display_name: '',
    role: 'user',
    scopeMode: 'all',
    organizations: '',
    regions: '',
  }
}

const canSubmit = computed(() => (
  form.username.trim()
  && form.password.length >= 8
  && !saving.value
))

async function reload() {
  loading.value = true
  try {
    const result = await api.users()
    users.value = result.items || []
  } catch (error) {
    showToast('账号列表加载失败：' + error.message)
  } finally {
    loading.value = false
  }
}

function startCreate() {
  Object.assign(form, emptyForm())
  creating.value = !creating.value
}

function splitValues(value) {
  return value.split(/[,，]/).map(item => item.trim()).filter(Boolean)
}

async function save() {
  if (!canSubmit.value) return
  saving.value = true
  try {
    const body = {
      username: form.username.trim(),
      password: form.password,
      display_name: form.display_name.trim() || form.username.trim(),
      role: form.role,
      data_scope: { mode: form.scopeMode, organizations: [], regions: [] },
    }
    if (form.scopeMode === 'restricted') {
      body.data_scope.organizations = splitValues(form.organizations)
      body.data_scope.regions = splitValues(form.regions)
    }
    await api.createUser(body)
    showToast(`已创建账号「${body.username}」`)
    creating.value = false
    Object.assign(form, emptyForm())
    await reload()
  } catch (error) {
    showToast('创建失败：' + error.message)
  } finally {
    saving.value = false
  }
}

onMounted(reload)
</script>

<template>
  <div class="page-shell wide-page">
    <div class="users-page">
      <header class="page-head">
        <div>
          <div class="eyebrow">权限</div>
          <h1>账号管理</h1>
          <p>管理员可以在这里添加业务用户和协作角色。密码不会回显；数据范围决定这个人能查哪些业务数据。</p>
        </div>
        <button class="btn-p" type="button" @click="startCreate">{{ creating ? '关闭表单' : '＋ 添加用户' }}</button>
      </header>

      <form v-if="creating" class="panel user-editor" @submit.prevent="save">
        <div class="editor-head">
          <div><span>新建</span><h2>添加用户</h2></div>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>用户名</span>
            <input v-model="form.username" autocomplete="off" maxlength="64" placeholder="登录账号" />
          </label>
          <label class="field">
            <span>显示名</span>
            <input v-model="form.display_name" maxlength="128" placeholder="可选，默认与用户名相同" />
          </label>
          <label class="field">
            <span>密码</span>
            <input v-model="form.password" type="password" autocomplete="new-password" placeholder="至少 8 位" />
          </label>
          <label class="field">
            <span>角色</span>
            <select v-model="form.role">
              <option value="user">业务用户</option>
              <option value="admin">管理员</option>
              <option value="knowledge_reviewer">知识审核员</option>
              <option value="data_source_admin">数据源管理员</option>
            </select>
          </label>
          <label class="field">
            <span>数据范围</span>
            <select v-model="form.scopeMode">
              <option value="all">全部数据</option>
              <option value="deny">拒绝访问</option>
              <option value="restricted">按组织 / 区域</option>
            </select>
          </label>
          <template v-if="form.scopeMode === 'restricted'">
            <label class="field">
              <span>组织</span>
              <input v-model="form.organizations" placeholder="逗号分隔，例如 TOP-SECRET-ORG" />
            </label>
            <label class="field span-2">
              <span>区域</span>
              <input v-model="form.regions" placeholder="逗号分隔，例如 华东, 华南" />
            </label>
          </template>
        </div>
        <div class="form-actions">
          <button class="btn-p" type="submit" :disabled="!canSubmit">{{ saving ? '正在创建…' : '创建账号' }}</button>
          <button class="btn-g" type="button" @click="creating = false">取消</button>
          <span>创建后即可用该账号登录。</span>
        </div>
      </form>

      <div v-if="loading" class="loading-state compact">正在读取账号…</div>
      <div v-else-if="!users.length" class="empty-state">
        <b>还没有账号</b>
        <span>先添加一个业务用户，再把登录信息交给对应的人。</span>
      </div>
      <section v-else class="user-list">
        <article v-for="user in users" :key="user.id" class="panel user-row">
          <div class="user-avatar">{{ (user.display_name || user.username).slice(0, 1) }}</div>
          <div class="user-copy">
            <strong>{{ user.display_name || user.username }}</strong>
            <code>{{ user.username }}</code>
          </div>
          <span class="status-badge" :class="user.role === 'admin' ? 'active' : ''">{{ ROLE_LABEL[user.role] || user.role }}</span>
          <span class="scope-chip">{{ SCOPE_LABEL[user.data_scope?.mode] || user.data_scope?.mode }}</span>
          <span class="user-meta">{{ user.is_active ? '启用' : '停用' }} · {{ formatDate(user.created_at) }}</span>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.users-page { margin: 0 auto; max-width: 1120px; }
.user-editor { margin-bottom: 18px; padding: 18px 20px 16px; }
.editor-head { margin-bottom: 16px; }
.editor-head span { color: var(--ink-3); font-size: 12px; font-weight: 600; }
.editor-head h2 { font-size: 17px; font-weight: 650; letter-spacing: -.02em; margin-top: 2px; }
.user-list { display: grid; gap: 10px; }
.user-row {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: 40px minmax(0, 1.2fr) auto auto minmax(120px, .8fr);
  padding: 12px 16px;
}
.user-avatar {
  align-items: center;
  background: var(--accent-soft);
  border-radius: 50%;
  color: var(--accent-dark);
  display: flex;
  font-size: 14px;
  font-weight: 700;
  height: 40px;
  justify-content: center;
  width: 40px;
}
.user-copy { min-width: 0; }
.user-copy strong { display: block; font-size: 14px; }
.user-copy code { color: var(--ink-3); font-size: 12px; }
.scope-chip { color: var(--ink-2); font-size: 12px; }
.user-meta { color: var(--ink-3); font-size: 12px; text-align: right; }
@media (max-width: 760px) {
  .user-row { grid-template-columns: 40px 1fr; }
  .user-row .status-badge, .user-row .scope-chip, .user-row .user-meta { grid-column: 2; text-align: left; }
}
</style>
