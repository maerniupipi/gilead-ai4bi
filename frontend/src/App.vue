<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AccountBar from './components/AccountBar.vue'
import Sidebar from './components/Sidebar.vue'
import LoginModal from './components/LoginModal.vue'
import ChatbotLauncher from './views/ChatbotLauncher.vue'
import { store } from './store.js'

const route = useRoute()
const canRenderRoute = computed(() => {
  if (route.meta.requiresAuth && !store.token) return false
  return !route.meta.roles?.length || route.meta.roles.includes(store.user?.role)
})
const routeKey = computed(() => {
  const view = ['knowledge', 'admin-knowledge'].includes(route.name) ? route.path : route.fullPath
  return `${store.user?.id || 'guest'}:${store.chatbotId}:${view}`
})
const showLauncher = computed(() => Boolean(store.token) && (store.chatbotChooserOpen || (!store.chatbotId
  && !(route.name === 'chatbots' && store.user?.role === 'admin')
  && !(route.meta.standalone && store.token))))
</script>

<template>
  <ChatbotLauncher v-if="showLauncher" />
  <div v-else class="app">
    <Sidebar />
    <div class="main">
      <AccountBar />
      <router-view v-if="canRenderRoute" :key="routeKey" />
    </div>
  </div>
  <LoginModal v-if="store.loginOpen" />
  <div v-if="store.toast" class="toast">{{ store.toast }}</div>
</template>
