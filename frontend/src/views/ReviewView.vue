<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { formatDate, loadReviewCount, showToast } from '../store.js'

const items = ref([])
const published = ref([])
const loading = ref(true)
const drafts = reactive({})

async function reload() {
  loading.value = true
  try {
    const [queue, publishedItems] = await Promise.all([
      api.reviewQueue('pending_review'),
      api.publishedKnowledge(),
    ])
    items.value = queue
    published.value = publishedItems
    items.value.forEach((item) => {
      drafts[item.id] ||= { comment: '', editedContent: item.content, editing: false, pending: false }
    })
  } catch (error) { showToast('审核队列加载失败：' + error.message) }
  finally { loading.value = false }
  loadReviewCount()
}

function normalized(value) {
  return String(value || '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLocaleLowerCase()
}

function conflictsFor(item) {
  const fallback = published.value.filter((entry) => (
    entry.scope === item.scope
    && normalized(entry.domain_id) === normalized(item.domain_id)
    && normalized(entry.title) === normalized(item.title)
  ))
  return [...new Map([...(item.published_conflicts || []), ...fallback].map((entry) => [entry.id, entry])).values()]
}

function validity(item) {
  if (!item.valid_from && !item.valid_until) return '未设置长期边界'
  return `${item.valid_from ? formatDate(item.valid_from) : '立即生效'} — ${item.valid_until ? formatDate(item.valid_until) : '长期有效'}`
}

async function decide(item, decision) {
  const draft = drafts[item.id]
  if (draft.pending) return
  draft.pending = true
  try {
    if (decision === 'approve') {
      await api.approveKnowledge(item.id, {
        ...(draft.comment.trim() ? { comment: draft.comment.trim() } : {}),
        ...(draft.editing && draft.editedContent.trim() !== item.content ? { edited_content: draft.editedContent.trim() } : {}),
      })
      showToast('候选已通过并发布')
    } else {
      await api.rejectKnowledge(item.id, { ...(draft.comment.trim() ? { comment: draft.comment.trim() } : {}) })
      showToast('候选已驳回')
    }
    await reload()
  } catch (error) { showToast('审核操作失败：' + error.message) }
  finally { draft.pending = false }
}

onMounted(reload)
</script>

<template>
  <div class="page-shell">
    <header class="page-head"><div><div class="eyebrow">审核</div><h1>知识审核</h1><p>核验证据、适用范围与表达，批准后发布为共享知识版本。</p></div><span class="count-chip">{{ items.length }} 待处理</span></header>
    <div v-if="loading" class="loading-state">正在获取审核队列…</div>
    <div v-else-if="!items.length" class="empty-state panel"><b>审核队列已清空</b><span>新的业务知识候选会自动出现在这里。</span></div>
    <section v-else class="review-grid">
      <article v-for="(item, index) in items" :key="item.id" class="review-card">
        <header><span class="review-no">{{ String(index + 1).padStart(2, '0') }}</span><div><small>{{ item.scope }}<template v-if="item.domain_id"> / {{ item.domain_id }}</template></small><h2>{{ item.title }}</h2></div><time>{{ formatDate(item.created_at) }}</time></header>
        <div class="review-content">{{ item.content }}</div>
        <div class="review-rationale"><b>沉淀理由</b>{{ item.rationale }}</div>
        <dl class="review-context">
          <div><dt>来源问题</dt><dd>{{ item.source_question || '未关联原始问题' }}</dd></div>
          <div v-if="item.clarification_question || item.clarification_answer"><dt>澄清记录</dt><dd><span v-if="item.clarification_question">问：{{ item.clarification_question }}</span><span v-if="item.clarification_answer">答：{{ item.clarification_answer }}</span></dd></div>
          <div><dt>适用范围</dt><dd :class="{ missing: !item.applicability }">{{ item.applicability || '未声明，批准前请重点核验' }}</dd></div>
          <div><dt>有效期</dt><dd>{{ validity(item) }}</dd></div>
          <div v-if="item.source_run_id"><dt>来源运行</dt><dd><code>{{ item.source_run_id }}</code></dd></div>
        </dl>
        <div v-if="conflictsFor(item).length" class="review-conflicts">
          <b>已发布同键版本</b>
          <p>批准后将形成新版本，并替代以下当前版本：</p>
          <article v-for="entry in conflictsFor(item)" :key="entry.id"><span>v{{ entry.version }} · {{ formatDate(entry.published_at) }}</span><p>{{ entry.content }}</p></article>
        </div>
        <div v-if="item.evidence_refs?.length" class="evidence-list"><span v-for="refId in item.evidence_refs" :key="refId">{{ refId }}</span></div>
        <label class="field"><span>审核意见 <em>可选</em></span><input v-model="drafts[item.id].comment" placeholder="记录批准或驳回原因" /></label>
        <label class="edit-toggle"><input v-model="drafts[item.id].editing" type="checkbox" /> 发布前编辑正文</label>
        <textarea v-if="drafts[item.id].editing" v-model="drafts[item.id].editedContent" class="review-editor" rows="5"></textarea>
        <footer><button class="btn-p" :disabled="drafts[item.id].pending" @click="decide(item, 'approve')">批准发布</button><button class="btn-g danger" :disabled="drafts[item.id].pending" @click="decide(item, 'reject')">驳回</button><code>{{ item.id.slice(0, 12) }}</code></footer>
      </article>
    </section>
  </div>
</template>
