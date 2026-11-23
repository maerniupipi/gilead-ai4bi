<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { login, store } from '../store.js'

const characterName = computed(() => store.branding?.character_name || '小英')
const logoUrl = computed(() => store.branding?.logo_url || '/brand/gilead-bi.svg')
const botName = computed(() => store.chatbots.find(bot => bot.id === store.pendingChatbotId)?.name || '')
const xlsxMode = computed(() => store.chatbots.length === 1 && store.chatbots[0].personal_uploads)

const username = ref(store.user?.username || '')
const password = ref('')
const error = ref('')
const pending = ref(false)
const input = ref(null)
const canSubmit = computed(() => username.value.trim() && password.value.length >= 8 && !pending.value)

onMounted(() => nextTick(() => input.value?.focus()))

async function submit() {
  if (!canSubmit.value) return
  pending.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    password.value = ''
  } catch (reason) {
    error.value = reason.status === 401 ? '用户名或密码不正确' : reason.message
  } finally {
    pending.value = false
  }
}

function maybeClose(event) {
  if (store.token && event.target.classList.contains('veil')) store.loginOpen = false
}
</script>

<template>
  <div class="veil" @click="maybeClose">
    <form class="modal auth-modal" @submit.prevent="submit">
      <img class="mk xy-avatar" :src="logoUrl" :alt="characterName" />
      <div class="eyebrow">{{ characterName }}</div>
      <h3>{{ store.token ? '切换账号' : '欢迎回来' }}</h3>
      <p>{{ botName ? `登录后进入「${botName}」` : '登录你的业务账号，选择可用的 Chatbot。' }}</p>
      <label class="field auth-field">
        <span>账号</span>
        <input ref="input" v-model="username" autocomplete="username" placeholder="输入用户名" />
      </label>
      <label class="field auth-field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="current-password" placeholder="至少 8 位" />
      </label>
      <div v-if="error" class="form-error">{{ error }}</div>
      <button class="btn-p" :disabled="!canSubmit" type="submit">{{ pending ? '正在验证…' : '登录' }}</button>
      <button v-if="store.token" class="btn-text" type="button" @click="store.loginOpen = false">取消</button>
      <button v-else-if="!xlsxMode" class="btn-text" type="button" @click="store.loginOpen = false; store.pendingChatbotId = ''">← 返回选择业务助手</button>
      <small>令牌会保存在当前浏览器的 localStorage；请勿在公共设备上保持登录。</small>
    </form>
  </div>
</template>
