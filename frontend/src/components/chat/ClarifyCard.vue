<script setup>
import { computed, reactive, watch } from 'vue'
import { confirmClarify, retryClarificationStream } from '../../chat.js'
import { store } from '../../store.js'

const props = defineProps({
  clarify: { type: Object, required: true },
  msg: { type: Object, required: true },
})

function blankValue(group) {
  return {
    choiceId: group.multiSelect ? '' : (group.choices.find(choice => choice.recommended)?.id || ''),
    choiceIds: group.multiSelect ? group.choices.filter(choice => choice.recommended).map(choice => choice.id) : [],
    freeText: '',
  }
}

const values = reactive({})

function ensureValue(group) {
  const key = group.questionId
  if (!values[key]) values[key] = blankValue(group)
  return values[key]
}

function resetValues() {
  Object.keys(values).forEach(key => delete values[key])
  for (const group of props.clarify.groups || []) ensureValue(group)
}

resetValues()
watch(() => [props.clarify.caseId, props.clarify.groups], resetValues)

function parseConfirmed(text) {
  const items = []
  const pattern = /问[:：]\s*(.*?)\s*答[:：]\s*(.*?)(?=\s*问[:：]|$)/gs
  let match
  while ((match = pattern.exec(text || ''))) {
    const prompt = match[1].trim()
    const answer = match[2].trim()
    if (prompt && answer) items.push({ prompt, answer })
  }
  return items
}

const recap = computed(() => {
  if (props.clarify.recap?.length) return props.clarify.recap
  return parseConfirmed(props.clarify.confirmed)
})

function answered(group) {
  const value = ensureValue(group)
  return Boolean(value.choiceId || value.choiceIds?.length || value.freeText.trim())
}

function toggleMulti(group, choiceId) {
  const current = ensureValue(group)
  const next = current.choiceIds.includes(choiceId) ? current.choiceIds.filter(id => id !== choiceId) : [...current.choiceIds, choiceId]
  current.choiceIds = next
  current.freeText = ''
}

function valid(group) {
  return !group.required || answered(group)
}

function canSubmit() {
  return props.clarify.groups.every(valid) && props.clarify.groups.some(answered)
}

function submit() {
  if (!canSubmit()) return
  const selectedGroups = props.clarify.groups.filter(answered)
  const answers = selectedGroups.map((group) => {
    const value = ensureValue(group)
    return {
      question_id: group.questionId,
      ...(value.choiceId ? { choice_id: value.choiceId } : {}),
      ...(value.choiceIds?.length ? { choice_ids: value.choiceIds } : {}),
      ...(value.freeText.trim() ? { free_text: value.freeText.trim() } : {}),
    }
  })
  const recapItems = selectedGroups.map((group) => {
    const value = ensureValue(group)
    const selected = value.choiceIds?.length
      ? group.choices.filter(choice => value.choiceIds.includes(choice.id)).map(choice => choice.label).join('、')
      : group.choices.find(choice => choice.id === value.choiceId)?.label
    return { prompt: group.prompt, answer: selected || value.freeText }
  }).filter(item => item.answer)
  props.clarify.recap = recapItems
  confirmClarify(props.msg, answers, recapItems.map(item => item.answer).join(' · '))
}
</script>

<template>
  <section class="clarify" :class="{ done: Boolean(clarify.confirmed) }">
    <template v-if="!clarify.confirmed">
      <div class="card-kicker">想跟你确认一下</div>
      <h4>{{ clarify.title }}</h4>
      <div v-for="group in clarify.groups" :key="group.questionId" class="clarify-group">
        <div class="cgroup">{{ group.prompt }} <span v-if="group.required">必填</span></div>
        <p v-if="group.why" class="clarify-why">{{ group.why }}</p>
        <div v-if="group.choices.length" class="opts">
          <button
            v-for="choice in group.choices"
            :key="choice.id"
            type="button"
            class="opt"
            :class="{ sel: group.multiSelect ? ensureValue(group).choiceIds.includes(choice.id) : ensureValue(group).choiceId === choice.id }"
            @click="group.multiSelect ? toggleMulti(group, choice.id) : (ensureValue(group).choiceId = choice.id, ensureValue(group).freeText = '')"
          >
            <strong>{{ choice.label }}<em v-if="choice.recommended"> 推荐</em><em v-if="choice.source === 'personal_memory'"> · 按你的习惯</em></strong>
            <small v-if="choice.explanation">{{ choice.explanation }}</small>
          </button>
        </div>
        <input
          v-if="group.allowFreeText"
          v-model="ensureValue(group).freeText"
          class="free-text"
          placeholder="也可以填写字段含义、单位或具体口径"
          @input="ensureValue(group).choiceId = ''; ensureValue(group).choiceIds = []"
        />
      </div>
      <div class="cfoot">
        <button class="btn-p" :disabled="clarify.submitting || !canSubmit()" @click="submit">
          {{ clarify.submitting ? '提交中…' : '确认并继续' }}
        </button>
        <span class="gate">确认后按所选口径继续分析</span>
      </div>
    </template>
    <div v-else class="confirmed">
      <div class="confirmed-head">
        <span class="confirmed-mark">已确认</span>
        <span v-if="clarify.memorySaved" class="memory-note">已存入个人记忆</span>
      </div>
      <p v-if="recap.length" class="confirmed-list">
        <span v-for="(item, index) in recap" :key="index" :title="item.prompt">{{ item.answer }}</span>
      </p>
      <p v-else class="confirmed-summary">{{ clarify.confirmed }}</p>
      <div v-if="clarify.reconnectError" class="reconnect-error">
        {{ clarify.reconnectError }}
        <button class="btn-g" :disabled="msg.streamConnected || store.busy" @click="retryClarificationStream(msg)">重试接收事件</button>
      </div>
    </div>
  </section>
</template>
