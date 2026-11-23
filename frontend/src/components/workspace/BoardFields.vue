<script setup>
import { BOARD_THEMES } from '../../workspace.js'
defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])
function update(key, value, form) { emit('update:modelValue', { ...form, [key]: value }) }
</script>
<template>
  <label class="ws-field"><span>看板名称</span><input :value="modelValue.name" required maxlength="64" placeholder="例如：季度商业经营看板" @input="update('name', $event.target.value, modelValue)" /></label>
  <label class="ws-field"><span>关注的业务主题</span><textarea :value="modelValue.description" rows="3" maxlength="1000" placeholder="描述这个看板关注的指标、问题或团队" @input="update('description', $event.target.value, modelValue)" /></label>
  <div class="ws-field"><span>看板主题</span><div class="ws-theme-picker"><button v-for="theme in BOARD_THEMES" :key="theme.id" type="button" :class="[theme.id, { selected: modelValue.theme === theme.id }]" :aria-pressed="modelValue.theme === theme.id" @click="update('theme', theme.id, modelValue)"><i></i><b>{{ theme.name }}</b><small>{{ theme.caption }}</small></button></div></div>
</template>
