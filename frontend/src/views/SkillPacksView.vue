<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { showToast } from '../store.js'

const TYPE_LABEL = {
  sql_generate: 'SQL生成',
  data_insight: '数据洞察技能包',
}

const items = ref([])
const loading = ref(true)
const openId = ref('')
const createOpen = ref(false)
const saving = ref(false)
const form = reactive({
  name: '',
  type: 'data_insight',
  prompt: '',
  blurb: '',
})

const current = computed(() => items.value.find(item => item.id === openId.value) || null)

async function reload() {
  loading.value = true
  try {
    const result = await api.skillPacks()
    items.value = result.items || []
  } catch (error) {
    showToast(error.message || '技能包加载失败')
  } finally {
    loading.value = false
  }
}

function open(id) {
  openId.value = id
}

function close() {
  openId.value = ''
}

function openCreate() {
  form.name = ''
  form.type = 'data_insight'
  form.prompt = ''
  form.blurb = ''
  createOpen.value = true
}

async function submitCreate() {
  if (!form.name.trim() || !form.prompt.trim()) {
    showToast('请填写名称与提示词')
    return
  }
  saving.value = true
  try {
    await api.createSkillPack({
      name: form.name.trim(),
      type: 'data_insight',
      prompt: form.prompt.trim(),
      blurb: form.blurb.trim(),
    })
    createOpen.value = false
    showToast('已添加技能包')
    await reload()
  } catch (error) {
    showToast(error.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function removePack(pack) {
  if (!pack?.editable) return
  if (!window.confirm(`确定删除「${pack.name}」？`)) return
  try {
    await api.deleteSkillPack(pack.id)
    close()
    showToast('已删除')
    await reload()
  } catch (error) {
    showToast(error.message || '删除失败')
  }
}

function onKey(event) {
  if (event.key === 'Escape') {
    close()
    createOpen.value = false
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
        <h1>技能包</h1>
        <p>内置 DDI分析 与 html模板，可编辑分析口径和报告呈现规则。洞察与查数共用取数链路。</p>
      </div>
      <div class="head-actions">
        <span class="count-chip">{{ items.length }} 个</span>
        <button class="btn-p" type="button" @click="openCreate">添加技能包</button>
      </div>
    </header>

    <div v-if="loading" class="loading-state">加载中…</div>
    <section v-else class="card-grid">
      <article
        v-for="pack in items"
        :key="pack.id"
        class="panel pack-card"
        role="button"
        tabindex="0"
        @click="open(pack.id)"
        @keydown.enter.prevent="open(pack.id)"
      >
        <div class="pack-icon">技</div>
        <div class="pack-title">
          <div>
            <h2>{{ pack.name }}</h2>
            <span class="status-badge" :class="pack.status === 'active' ? 'ok' : 'pending'">
              {{ TYPE_LABEL[pack.type] || pack.type }}
            </span>
          </div>
          <code>{{ pack.id }}</code>
        </div>
        <p class="pack-blurb">{{ pack.blurb || '（无简介）' }}</p>
        <span class="pack-more">查看说明</span>
      </article>
    </section>

    <div v-if="current" class="veil" @click.self="close">
      <div class="detail-modal" role="dialog" aria-modal="true">
        <header class="detail-head">
          <div class="pack-icon">技</div>
          <div>
            <div>
              <h2>{{ current.name }}</h2>
              <span class="status-badge" :class="current.status === 'active' ? 'ok' : 'pending'">
                {{ TYPE_LABEL[current.type] || current.type }}
              </span>
            </div>
            <code>{{ current.id }}</code>
          </div>
        </header>
        <p class="detail-copy">{{ current.blurb || '（无简介）' }}</p>
        <section class="detail-block">
          <h3>提示词</h3>
          <pre>{{ current.prompt || '（空）' }}</pre>
        </section>
        <footer class="detail-actions">
          <button
            v-if="current.editable"
            class="btn-g"
            type="button"
            @click="removePack(current)"
          >删除</button>
          <button class="btn-p" type="button" @click="close">关闭</button>
        </footer>
      </div>
    </div>

    <div v-if="createOpen" class="veil" @click.self="createOpen = false">
      <div class="detail-modal" role="dialog" aria-modal="true">
        <header class="detail-head">
          <div>
            <h2>添加技能包</h2>
            <p class="hint">当前仅支持「数据洞察技能包」，将出现在聊天洞察模式的加载 skill 弹窗中。</p>
          </div>
        </header>
        <label class="field">
          <span>名称</span>
          <input v-model="form.name" type="text" maxlength="160" placeholder="例如：区域销售洞察" />
        </label>
        <label class="field">
          <span>类型</span>
          <select v-model="form.type" disabled>
            <option value="data_insight">数据洞察技能包</option>
          </select>
        </label>
        <label class="field">
          <span>简介</span>
          <input v-model="form.blurb" type="text" maxlength="2000" placeholder="给业务同事看的一句话说明" />
        </label>
        <label class="field">
          <span>提示词</span>
          <textarea v-model="form.prompt" rows="8" placeholder="指导模型如何拆分 KPI、下钻与归因…" />
        </label>
        <footer class="detail-actions">
          <button class="btn-g" type="button" @click="createOpen = false">取消</button>
          <button class="btn-p" type="button" :disabled="saving" @click="submitCreate">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fill-page { padding: 28px 28px 48px; }
.fill-page .page-head { margin: 0 0 22px; max-width: none; }
.head-actions { align-items: center; display: flex; gap: 10px; }
.card-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.pack-card {
  cursor: pointer;
  display: grid;
  gap: 10px;
  grid-template-columns: 40px 1fr;
  min-height: 168px;
  padding: 16px 18px;
  transition: border-color .15s, transform .15s;
}
.pack-card:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
  transform: translateY(-1px);
}
.pack-icon {
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
.pack-title { min-width: 0; }
.pack-title > div { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
.pack-title h2 { font-size: 15px; margin: 0; }
.pack-title code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.pack-blurb {
  color: var(--ink-3);
  font-size: 12.5px;
  grid-column: 1 / -1;
  line-height: 1.55;
}
.pack-more {
  color: var(--ink-3);
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
.detail-head h2 { font-size: 20px; font-weight: 650; letter-spacing: -.02em; margin: 0; }
.detail-head code { color: var(--ink-2); display: block; font-size: 12px; margin-top: 3px; }
.detail-copy { color: var(--ink-2); font-size: 13px; line-height: 1.65; margin-bottom: 16px; }
.detail-block + .detail-block { margin-top: 16px; }
.detail-block h3 { color: var(--ink-3); font-size: 11px; font-weight: 650; margin-bottom: 8px; }
.detail-block pre {
  background: var(--bg);
  border-radius: 12px;
  color: var(--ink-2);
  font-size: 12.5px;
  line-height: 1.55;
  margin: 0;
  max-height: 280px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.detail-actions {
  border-top: 1px solid var(--line);
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 18px;
  padding-top: 14px;
}
.hint { color: var(--ink-3); font-size: 12.5px; line-height: 1.5; margin: 6px 0 0; }
.field { display: grid; gap: 6px; margin-bottom: 12px; }
.field > span { color: var(--ink-3); font-size: 11px; font-weight: 650; }
.field input, .field select, .field textarea {
  border: 1px solid var(--line);
  border-radius: 10px;
  font: 13px/1.45 var(--body-font);
  padding: 9px 11px;
  width: 100%;
}
.field textarea { min-height: 160px; resize: vertical; }
.status-badge.ok {
  background: var(--accent-soft);
  color: var(--accent-dark);
}
@media (max-width: 760px) {
  .fill-page { padding: 20px 16px 40px; }
}
</style>
