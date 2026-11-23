<script setup>
import { ref } from 'vue'
import { api } from '../../api/backend.js'
import WorkspaceDialog from './WorkspaceDialog.vue'
import BoardFields from './BoardFields.vue'
const props = defineProps({ board: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])
const form = ref({ name: props.board?.name || '', description: props.board?.description || '', theme: props.board?.theme || 'commercial' })
const saving = ref(false), error = ref('')
async function save() {
  if (saving.value || !form.value.name.trim()) return
  saving.value = true; error.value = ''
  try { emit('saved', props.board ? await api.updateWorkspaceBoard(props.board.id, { ...form.value, version: props.board.version }) : await api.createWorkspaceBoard(form.value)) }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
</script>
<template><WorkspaceDialog :title="board ? '编辑主题看板' : '创建主题看板'" subtitle="把重要的业务发现，汇集成团队可持续查看的看板。" :busy="saving" @close="emit('close')"><form @submit.prevent="save"><div class="ws-dialog-body"><BoardFields v-model="form" /><p v-if="error" class="ws-error" role="alert">{{ error }}</p></div><footer class="ws-dialog-footer"><span>创建后默认仅自己可见</span><button type="button" class="ws-button" :disabled="saving" @click="emit('close')">取消</button><button class="ws-button primary" :disabled="saving || !form.name.trim()">{{ saving ? '保存中…' : board ? '保存修改' : '创建看板' }}</button></footer></form></WorkspaceDialog></template>
