import { createRouter, createWebHashHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import ReviewView from './views/ReviewView.vue'
import TraceView from './views/TraceView.vue'
import DataSourcesView from './views/DataSourcesView.vue'
import ModelsView from './views/ModelsView.vue'
import ToolsView from './views/ToolsView.vue'
import LabConnectionView from './views/LabConnectionView.vue'
import AgentsView from './views/AgentsView.vue'
import SkillPacksView from './views/SkillPacksView.vue'
import BrandingView from './views/BrandingView.vue'
import UsersView from './views/UsersView.vue'
import UsageView from './views/UsageView.vue'
import OpsBoardView from './views/OpsBoardView.vue'
import ChatbotsView from './views/ChatbotsView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import { setAuthNavigationHandler, showToast, store } from './store.js'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/workspace', name: 'workspace', component: WorkspaceView, meta: { requiresAuth: true, standalone: true } },
    { path: '/workspace/:id', name: 'workspace-board', component: WorkspaceView, meta: { requiresAuth: true, standalone: true } },
    { path: '/chatbots', name: 'chatbots', component: ChatbotsView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/', name: 'chat', component: ChatView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView, meta: { requiresAuth: true, standalone: true } },
    { path: '/admin/knowledge', name: 'admin-knowledge', component: KnowledgeView, meta: { requiresAuth: true, standalone: true, roles: ['admin', 'knowledge_reviewer'] } },
    { path: '/trace', name: 'trace', component: TraceView, meta: { requiresAuth: true } },
    { path: '/review', name: 'review', component: ReviewView, meta: { requiresAuth: true, roles: ['admin', 'knowledge_reviewer'] } },
    { path: '/data-sources', name: 'data-sources', component: DataSourcesView, meta: { requiresAuth: true, roles: ['admin', 'data_source_admin'] } },
    { path: '/models', name: 'models', component: ModelsView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/tools', name: 'tools', component: ToolsView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/lab-connection', name: 'lab-connection', component: LabConnectionView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/agents', name: 'agents', component: AgentsView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/skill-packs', name: 'skill-packs', component: SkillPacksView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/branding', name: 'branding', component: BrandingView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/users', name: 'users', component: UsersView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/usage', name: 'usage', component: UsageView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/ops', name: 'ops', component: OpsBoardView, meta: { requiresAuth: true, roles: ['admin'] } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !store.token) {
    store.loginOpen = true
    showToast('请先登录后继续')
    return { name: 'chat', query: { login: '1', next: to.fullPath } }
  }
  if (to.meta.roles?.length && !to.meta.roles.includes(store.user?.role)) {
    showToast('当前账号没有访问该页面的权限')
    return { name: 'chat' }
  }
  if (to.meta.standalone && store.token) store.chatbotChooserOpen = false
  return true
})

setAuthNavigationHandler(() => {
  const current = router.currentRoute.value
  const next = current.query.next
  if (store.token && typeof next === 'string' &&
      (/^\/workspace(?:\/[^/?#]+)?$/.test(next) || ['/knowledge', '/admin/knowledge'].includes(next.split('?')[0]))) {
    store.chatbotChooserOpen = false
    router.replace(next).catch(() => {})
    return
  }
  const lacksAuth = current.meta.requiresAuth && !store.token
  const lacksRole = current.meta.roles?.length && !current.meta.roles.includes(store.user?.role)
  if (lacksAuth || lacksRole) router.replace({ name: 'chat' }).catch(() => {})
})
