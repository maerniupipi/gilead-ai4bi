<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/backend.js'
import { showToast } from '../../store.js'
import { boardPath, canEditBoard } from '../../workspace.js'
import WorkspaceDialog from './WorkspaceDialog.vue'
import BoardFields from './BoardFields.vue'
const props = defineProps({ source: { type: Object, required: true }, title: { type: String, default: '' } })
const emit = defineEmits(['close'])
const router = useRouter()
const boards = ref([]), selected = ref(''), search = ref(''), creating = ref(false), loading = ref(true), busy = ref(false), error = ref(''), saved = ref(null)
const title = ref(props.title.slice(0, 120))
const subtitle = computed(() => props.source.kind === 'answer_analysis'
  ? '保存整块分析，包含标题、关键指标、可切换的图表和数据表。'
  : '保留所选图表或数据表，以及对应的统计范围。')
const form = ref({ name: '', description: '', theme: 'commercial' })
const visible = computed(() => boards.value.filter(board => `${board.name} ${board.description}`.toLowerCase().includes(search.value.toLowerCase())))
async function load() {
  loading.value = true; error.value = ''
  try { boards.value = (await api.workspaceBoards()).items.filter(canEditBoard); selected.value = boards.value[0]?.id || ''; creating.value = !boards.value.length }
  catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}
async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const pin = { ...props.source, title: title.value.trim() }
    if (creating.value) saved.value = await api.createWorkspaceBoard({ ...form.value, pin })
    else {
      const result = await api.pinWorkspaceItem(selected.value, pin)
      saved.value = result.board
      if (result.already_added) showToast('这项内容及筛选已在看板中')
    }
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
function openBoard() { emit('close'); void router.push(boardPath(saved.value.id)) }
onMounted(load)
</script>
<template>
  <WorkspaceDialog :title="saved ? '已加入主题看板' : '加入看板'" :subtitle="subtitle" :busy="busy" @close="emit('close')">
    <div v-if="saved" class="ws-pin-success"><span>✓</span><h3>{{ saved.name }}</h3><p>内容已保存。你可以在工作台调整布局，并授权给团队成员。</p><div><button class="ws-button" @click="emit('close')">继续分析</button><button class="ws-button primary" @click="openBoard">查看看板 →</button></div></div>
    <form v-else @submit.prevent="save"><div class="ws-dialog-body"><label class="ws-field"><span>内容在看板中的标题</span><input v-model="title" maxlength="120" placeholder="保留原标题" /></label><div class="ws-pin-tabs"><button type="button" :class="{ on: !creating }" @click="creating = false">已有看板</button><button type="button" :class="{ on: creating }" @click="creating = true">＋ 新建看板</button></div><BoardFields v-if="creating" v-model="form" /><template v-else><input v-model="search" class="ws-search" aria-label="搜索可编辑看板" placeholder="搜索可编辑的看板" /><p v-if="loading" class="ws-empty">正在读取看板…</p><div v-else class="ws-pin-list"><label v-for="board in visible" :key="board.id" :class="{ selected: selected === board.id }"><input v-model="selected" type="radio" name="pin-board" :value="board.id" /><span><b>{{ board.name }}</b><small>{{ board.description || '主题看板' }}</small></span><em>{{ board.card_count }} 项内容</em></label><p v-if="!visible.length" class="ws-empty">没有匹配的可编辑看板，可以新建一个。</p></div></template><p class="ws-help">保存的是当前数据快照，原问答更新后不会自动覆盖。仅可加入你有编辑权限的看板。</p><p v-if="error" class="ws-error" role="alert">{{ error }}<button v-if="loading" type="button" @click="load">重试</button></p></div><footer class="ws-dialog-footer"><button type="button" class="ws-button" :disabled="busy" @click="emit('close')">取消</button><button class="ws-button primary" :disabled="busy || loading || (creating ? !form.name.trim() : !selected)">{{ busy ? '保存中…' : creating ? '创建并加入看板' : '加入看板' }}</button></footer></form>
  </WorkspaceDialog>
</template>
