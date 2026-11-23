<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { currentChatbot, isSessionLive, logout, newChat, openChatbotChooser, openSession, showToast, store } from '../store.js'
import NavIcon from './NavIcon.vue'
import QuestionHistoryModal from './QuestionHistoryModal.vue'

const route = useRoute()
const router = useRouter()
const displayName = computed(() => store.user?.display_name || store.user?.username || '未登录')
const initials = computed(() => displayName.value.slice(0, 1).toUpperCase())
const roleLabel = computed(() => ({ admin: '管理员', knowledge_reviewer: '知识审核员', data_source_admin: '数据源管理员', user: '业务用户' })[store.user?.role] || store.user?.role || '未登录')
const chatbot = computed(currentChatbot)
const xlsxMode = computed(() => Boolean(chatbot.value?.personal_uploads))
const singleXlsxMode = computed(() => xlsxMode.value && store.chatbots.length === 1)
const userMenuOpen = ref(false)
const userArea = ref(null)

const characterName = computed(() => store.branding?.character_name || 'Gilead BI')
const companyIntro = computed(() => store.branding?.company_intro || '吉利德业务助手')
const logoUrl = computed(() => store.branding?.logo_url || '/brand/gilead-bi.svg')
const adminLinks = computed(() => {

  const links = []
  if (store.user?.role === 'admin') {
    links.push({ to: '/chatbots', name: 'chatbots', icon: 'chat', label: 'Chatbot 管理' })
    links.push({ to: '/branding', name: 'branding', icon: 'brand', label: '品牌配置' })
    links.push({ to: '/users', name: 'users', icon: 'users', label: '账号管理' })
  }
  if (['admin', 'knowledge_reviewer'].includes(store.user?.role)) {
    links.push({ to: '/admin/knowledge', name: 'admin-knowledge', icon: 'knowledge', label: '知识库' })
    links.push({ to: '/review', name: 'review', icon: 'review', label: '知识审核' })
  }
  if (['admin', 'data_source_admin'].includes(store.user?.role)) links.push({ to: '/data-sources', name: 'data-sources', icon: 'source', label: '数据源' })
  if (store.user?.role === 'admin') {
    links.push({ to: '/agents', name: 'agents', icon: 'agent', label: '问数助手' })
    links.push({ to: '/tools', name: 'tools', icon: 'tool', label: '工具目录' })
    links.push({ to: '/lab-connection', name: 'lab-connection', icon: 'lab', label: '实验室连接' })
    links.push({ to: '/skill-packs', name: 'skill-packs', icon: 'pack', label: '技能包' })
    links.push({ to: '/models', name: 'models', icon: 'model', label: '模型管理' })
    links.push({ to: '/usage', name: 'usage', icon: 'usage', label: 'Token 消耗' })
    links.push({ to: '/ops', name: 'ops', icon: 'ops', label: '运维看板' })
  }
  return links
})
const adminRouteNames = new Set(['chatbots', 'branding', 'users', 'admin-knowledge', 'review', 'data-sources', 'models', 'agents', 'tools', 'lab-connection', 'skill-packs', 'usage', 'ops'])
const onAdminRoute = computed(() => adminRouteNames.has(route.name))
const adminOpen = ref(false)
const historyOpen = ref(false)
watch(() => route.name, (name) => {
  adminOpen.value = adminRouteNames.has(name)
  userMenuOpen.value = false
}, { immediate: true })
watch(() => store.token, (token) => {
  if (!token) historyOpen.value = false
})

function toggleAdmin() {
  adminOpen.value = !adminOpen.value
}

function switchChatbot() {
  userMenuOpen.value = false
  openChatbotChooser()
}
function onOutside(event) {
  if (!userArea.value?.contains(event.target)) userMenuOpen.value = false
}
function onEscape(event) { if (event.key === 'Escape') userMenuOpen.value = false }
onMounted(() => { document.addEventListener('click', onOutside); document.addEventListener('keydown', onEscape) })
onUnmounted(() => { document.removeEventListener('click', onOutside); document.removeEventListener('keydown', onEscape) })

async function onNewChat() {
  newChat()
  await router.push('/')
}

async function selectSession(session) {
  try {
    await Promise.all([openSession(session.id), router.push('/')])
  } catch (error) {
    showToast('会话加载失败：' + error.message)
  }
}
</script>

<template>
  <aside class="side" :class="{ 'xlsx-sidebar': xlsxMode }">
    <div class="brand">
      <img class="brand-mark" :src="logoUrl" :alt="characterName" />
      <div><strong>{{ characterName }}</strong><span>{{ companyIntro }}</span></div>
    </div>
    <div v-if="singleXlsxMode" class="sidebar-chatbot fixed-chatbot"><NavIcon name="source" /><span><small>专属数据空间</small><b>XLSX 问数助手</b></span></div>
    <button v-else class="sidebar-chatbot" :title="`当前助手：${chatbot?.name || '请选择'}，点击切换`" @click="switchChatbot"><NavIcon name="chat" /><span><small>当前业务助手</small><b>{{ chatbot?.name || '选择 Chatbot' }}</b></span><span class="switch-symbol">⇄</span></button>
    <button class="newchat" title="新对话" aria-label="新对话" :disabled="!store.token" @click="onNewChat"><NavIcon name="plus" /> 新对话</button>

    <nav class="nav">
      <template v-if="onAdminRoute && adminLinks.length">
        <button class="nav-group" type="button" :aria-expanded="adminOpen" :class="{ open: adminOpen, on: onAdminRoute && !adminOpen }" @click="toggleAdmin">
          <NavIcon name="admin" />管理员
          <span class="nav-group-end">
            <span v-if="store.reviewPending && !adminOpen" class="qn">{{ store.reviewPending }}</span>
            <NavIcon name="chevron" class="nav-chev" />
          </span>
        </button>
        <div v-show="adminOpen" class="nav-sub">
          <router-link v-for="item in adminLinks" :key="item.name" :to="item.to" :title="item.label" :aria-label="item.label" :class="{ on: route.name === item.name }">
            <NavIcon :name="item.icon" />{{ item.label }}
            <span v-if="item.name === 'review' && store.reviewPending" class="qn">{{ store.reviewPending }}</span>
          </router-link>
        </div>
      </template>

      <template v-if="!onAdminRoute && store.sessions.length">
        <div class="nav-label recent-head">
          <span>最近会话</span>
          <button class="nav-more" type="button" aria-label="查看全部提问" @click="historyOpen = true">更多</button>
        </div>
        <button v-for="session in store.sessions.slice(0, 8)" :key="session.id" class="recent" :class="{ on: store.sessionId === session.id, live: isSessionLive(session.id) }" @click="selectSession(session)">
          <span class="session-dot"></span><span>{{ session.title || '未命名会话' }}</span>
        </button>
      </template>
    </nav>

</aside>
  <Teleport to="body">
    <QuestionHistoryModal v-if="historyOpen" @close="historyOpen = false" />
  </Teleport>
</template>

<style scoped>
.side{position:relative;z-index:20}
.fixed-chatbot{cursor:default}
@media (max-width: 760px) {
  .side .nav .nav-group, .side .nav .nav-sub a { display: flex; justify-content: center; padding-inline: 4px; font-size: 0; gap: 0; }
  .side .nav .nav-sub { display: block; padding-left: 0; }
  .nav-group-end { display: none; }
}
@media(max-width:760px){.xlsx-sidebar .newchat{display:flex;justify-content:center;font-size:0;padding:10px;margin:0 0 8px;min-height:38px}.xlsx-sidebar .newchat .nav-icon{height:17px;width:17px}}
.sidebar-chatbot{margin:0 14px 13px;padding:10px;display:flex;align-items:center;gap:9px;border:1px solid #e8e3e8;background:#ffffffaa;border-radius:12px;color:#af344d;cursor:pointer;min-width:0;text-align:left;flex-shrink:0}.sidebar-chatbot>.nav-icon{width:18px;height:18px}.sidebar-chatbot>span:nth-child(2){min-width:0;flex:1}.sidebar-chatbot small{font-size:8px;display:block;color:#ab9da6;margin-bottom:4px}.sidebar-chatbot b{font-size:10px;font-weight:600;color:#685462;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.switch-symbol{font-size:17px;color:#c4b4bf}.account-popover{position:fixed;bottom:78px;left:14px;width:212px;padding:7px;background:#fff;border:1px solid #e5dce3;border-radius:15px;box-shadow:0 14px 50px #3e193323;z-index:100}.account-context{padding:10px 10px 13px;border-bottom:1px solid #f1ecf0;margin-bottom:4px}.account-context small{font-size:8px;color:#a99da9;display:block;margin-bottom:5px}.account-context b{font-size:12px;font-weight:600;color:#6b5263;display:block;overflow-wrap:anywhere}.account-popover>button{display:flex;align-items:center;gap:9px;padding:10px;width:100%;background:transparent;border:0;border-radius:8px;font-size:11px;color:#776370;cursor:pointer;text-align:left}.account-popover>button:hover{background:#fcf2f5;color:#b72646}.account-popover>button .nav-icon{height:16px;width:16px}.account-popover>button>span{margin-left:auto;color:#b6a0ae}.account-popover>button.account-signout{border-top:1px solid #f3edf2;border-radius:0;margin-top:4px;padding-top:12px;color:#ac7c8e}@media(max-width:900px){.sidebar-chatbot{margin:0 7px 10px;padding:11px 10px;justify-content:center}.sidebar-chatbot>span{display:none}.account-popover{left:8px;bottom:68px;width:220px}}
</style>
