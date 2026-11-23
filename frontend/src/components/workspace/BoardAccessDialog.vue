<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../../api/backend.js'
import { boardLink } from '../../workspace.js'
import { showToast } from '../../store.js'
import WorkspaceDialog from './WorkspaceDialog.vue'
const props = defineProps({ board: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved'])
const members = ref([]), owner = ref(null), version = ref(0), query = ref(''), people = ref([]), loading = ref(true), searching = ref(false), saving = ref(false), error = ref('')
let timer, request = 0
const candidates = computed(() => people.value.filter(person => person.id !== owner.value?.id && !members.value.some(member => member.user_id === person.id)))
async function search() {
  const seq = ++request; searching.value = true
  try { const result = await api.workspacePeople({ search: query.value }); if (seq === request) people.value = result.items }
  catch (cause) { if (seq === request) error.value = cause.message }
  finally { if (seq === request) searching.value = false }
}
async function load() {
  try { const result = await api.workspaceAccess(props.board.id); members.value = result.members; owner.value = result.owner; version.value = result.version; await search() }
  catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}
function add(user) { members.value.push({ user_id: user.id, role: 'viewer', user }) }
async function save() {
  saving.value = true; error.value = ''
  try { const board = await api.saveWorkspaceAccess(props.board.id, { version: version.value, members: members.value.map(({ user_id, role }) => ({ user_id, role })) }); emit('saved', board); showToast('看板授权已更新') }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function copy() { try { await navigator.clipboard.writeText(boardLink(props.board.id)); showToast('链接已复制，仅获授权的账号可访问') } catch { error.value = '无法自动复制，请手动复制下方链接' } }
watch(query, () => { clearTimeout(timer); timer = setTimeout(search, 250) })
onMounted(load)
onBeforeUnmount(() => { clearTimeout(timer); request++ })
</script>
<template>
  <WorkspaceDialog title="分享与权限" :subtitle="board.name" :busy="saving" @close="emit('close')"><div class="ws-dialog-body"><div class="ws-share-note"><span>◈</span><p>授权整份看板及其中已保存的图表快照。<br /><small>原始对话与数据源查询权限由各自的权限配置决定。</small></p></div><div v-if="loading" class="ws-empty">正在读取授权…</div><template v-else><h3 class="ws-section-title">已授权成员 <span>{{ members.length + 1 }}</span></h3><div class="ws-member-row"><span class="ws-person-avatar">{{ (owner?.display_name || owner?.username || '我').slice(0,1) }}</span><span class="ws-person-name"><b>{{ owner?.display_name || owner?.username }}</b><small>{{ owner?.username }}</small></span><span class="ws-owner-badge">创建者</span></div><div v-for="member in members" :key="member.user_id" class="ws-member-row"><span class="ws-person-avatar">{{ (member.user?.display_name || member.user?.username || '?').slice(0,1) }}</span><span class="ws-person-name"><b>{{ member.user?.display_name || member.user?.username || '已移除账号' }}</b><small>{{ member.user?.is_active === false ? '账号已停用' : member.user?.username }}</small></span><select v-model="member.role" :aria-label="`${member.user?.username} 的看板权限`"><option value="viewer">可查看</option><option value="editor">可编辑</option></select><button type="button" class="ws-remove-member" :aria-label="`撤销${member.user?.username}的权限`" @click="members = members.filter(item => item.user_id !== member.user_id)">移除</button></div><h3 class="ws-section-title add-members-title">添加成员</h3><input v-model="query" class="ws-search" aria-label="搜索授权账号" placeholder="搜索账号或姓名" /><div class="ws-candidates"><p v-if="searching" class="ws-empty">搜索中…</p><button v-for="user in candidates" v-else :key="user.id" type="button" class="ws-candidate" :aria-label="`授权给${user.username}`" @click="add(user)"><span class="ws-person-avatar">{{ (user.display_name || user.username).slice(0,1) }}</span><span class="ws-person-name"><b>{{ user.display_name || user.username }}</b><small>{{ user.username }}</small></span><span>＋ 添加</span></button><p v-if="!searching && !candidates.length" class="ws-empty">没有匹配的可添加账号</p></div><p class="ws-help">可查看：浏览看板；可编辑：添加图表、编辑标题和布局。仅创建者可以管理授权。</p><div class="ws-share-link"><input :value="boardLink(board.id)" readonly aria-label="看板分享链接" /><button type="button" @click="copy">复制链接</button></div></template><p v-if="error" class="ws-error" role="alert">{{ error }}</p></div><footer class="ws-dialog-footer"><span>移除成员将在保存后生效</span><button class="ws-button" :disabled="saving" @click="emit('close')">取消</button><button class="ws-button primary" :disabled="saving || loading" @click="save">{{ saving ? '保存中…' : '保存授权' }}</button></footer></WorkspaceDialog>
</template>
