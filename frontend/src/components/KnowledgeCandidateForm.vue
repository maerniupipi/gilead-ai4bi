<script setup>
import { reactive, ref } from 'vue'
import { api } from '../api/backend.js'
import { showToast } from '../store.js'
const emit = defineEmits(['submitted','close'])
const saving = ref(false)
const form = reactive({
  scope: 'business', domain_id: '', title: '', content: '', rationale: '',
  evidence_refs: '', source_run_id: '', source_question: '', applicability: '',
  valid_from: '', valid_until: '',
})

async function submitCandidate() {
  if (saving.value) return
  saving.value = true
  try {
    await api.createKnowledgeCandidate({
      scope: form.scope,
      title: form.title.trim(),
      content: form.content.trim(),
      rationale: form.rationale.trim(),
      evidence_refs: form.evidence_refs.split(/[\n,]/).map(item => item.trim()).filter(Boolean),
      ...(form.scope === 'domain' ? { domain_id: form.domain_id.trim() } : {}),
      ...(form.source_run_id.trim() ? { source_run_id: form.source_run_id.trim() } : {}),
      ...(form.source_question.trim() ? { source_question: form.source_question.trim() } : {}),
      ...(form.applicability.trim() ? { applicability: form.applicability.trim() } : {}),
      ...(form.valid_from ? { valid_from: form.valid_from } : {}),
      ...(form.valid_until ? { valid_until: form.valid_until } : {}),
    })
    Object.assign(form, {
      scope: 'business', domain_id: '', title: '', content: '', rationale: '',
      evidence_refs: '', source_run_id: '', source_question: '', applicability: '',
      valid_from: '', valid_until: '',
    })
    showToast('知识候选已提交审核')
    emit('submitted')
  } catch (error) { showToast('提交失败：' + error.message) }
  finally { saving.value = false }
}

</script>

<template>
<form class="panel candidate-form" @submit.prevent="submitCandidate">
        <div class="form-grid">
          <label class="field"><span>作用域</span><select v-model="form.scope"><option value="business">全局业务</option><option value="domain">指定域</option></select></label>
          <label v-if="form.scope === 'domain'" class="field"><span>Domain ID</span><input v-model="form.domain_id" required placeholder="吉利德 DDI 域请填 actual（内部 id）" /></label>
          <label class="field span-2"><span>标题</span><input v-model="form.title" required maxlength="160" placeholder="一句话说明这条知识" /></label>
          <label class="field span-2"><span>知识内容 <em>支持 Markdown</em></span><textarea v-model="form.content" required rows="5" placeholder="写出可复用、无歧义的业务规则或定义。"></textarea></label>
          <label class="field span-2"><span>为什么值得沉淀</span><textarea v-model="form.rationale" required rows="3" placeholder="说明适用场景与复用价值。"></textarea></label>
          <label class="field"><span>证据引用 <em>逗号或换行分隔</em></span><textarea v-model="form.evidence_refs" rows="3" placeholder="fact_id / evidence_id"></textarea></label>
          <label class="field"><span>来源 Run ID <em>可选</em></span><input v-model="form.source_run_id" placeholder="关联运行" /></label>
          <label class="field span-2"><span>来源问题 <em>无 Run 时可填写</em></span><input v-model="form.source_question" maxlength="10000" placeholder="触发这条知识候选的原始问题" /></label>
          <label class="field span-2"><span>适用范围 <em>建议填写</em></span><textarea v-model="form.applicability" rows="2" placeholder="适用于哪些用户、业务域、场景和口径；不适用于什么情况。"></textarea></label>
          <label class="field"><span>生效时间 <em>可选</em></span><input v-model="form.valid_from" type="datetime-local" /></label>
          <label class="field"><span>失效时间 <em>可选</em></span><input v-model="form.valid_until" type="datetime-local" /></label>
        </div>
        <div class="form-actions"><button class="btn-p" :disabled="saving">{{ saving ? '提交中…' : '送审候选' }}</button><button type="button" class="btn-text" @click="emit('close')">取消</button></div>
      </form>
</template>
