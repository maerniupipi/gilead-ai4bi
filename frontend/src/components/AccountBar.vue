<script setup>
import { computed,onMounted,onBeforeUnmount,ref,watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/backend.js'
import { store,logout,openChatbotChooser } from '../store.js'
import NavIcon from './NavIcon.vue'
const route=useRoute(), quota=ref(null), error=ref(''), menu=ref(false), area=ref(null)
let epoch=0, timer
const name=computed(()=>store.user?.display_name || store.user?.username || '登录')
const number=n=>Number(n).toLocaleString('zh-CN')
const percent=computed(()=>quota.value ? Math.min(100,quota.value.used/quota.value.limit*100) : 0)
async function refresh(){
  const seq=++epoch
  if(!store.token){quota.value=null;return}
  try{const q=await api.myQuota();if(seq===epoch){quota.value=q;error.value=''}}
  catch{if(seq===epoch) error.value='额度暂时不可用'}
}
function outside(e){if(!area.value?.contains(e.target))menu.value=false}
watch(()=>[store.user?.id,store.busy],()=>{if(!store.busy)refresh()},{immediate:true})
watch(()=>route.path,()=>{menu.value=false})
onMounted(()=>{timer=setInterval(refresh,30000);document.addEventListener('click',outside);window.addEventListener('quota-updated',refresh)})
onBeforeUnmount(()=>{clearInterval(timer);document.removeEventListener('click',outside);window.removeEventListener('quota-updated',refresh)})
</script>
<template><header class="accountbar">
<nav aria-label="首页导航"><router-link to="/" :class="{active:route.name==='chat'}"><NavIcon name="chat"/>问数</router-link>
<router-link to="/workspace" :class="{active:route.path.startsWith('/workspace')}"><NavIcon name="grid"/>看板</router-link>
<router-link v-if="store.token" to="/knowledge" :class="{active:route.name==='knowledge'}"><NavIcon name="knowledge"/>知识库</router-link></nav>
<div ref="area" class="profile"><router-link v-if="store.user?.role==='admin'" class="gear" to="/chatbots" aria-label="管理" title="管理"><NavIcon name="admin"/></router-link>
<button type="button" class="user" :aria-expanded="menu" @click="store.token ? menu=!menu : store.loginOpen=true"><span class="ring" :style="{'--usage':percent+'%'}" :title="quota ? '本月 Token '+number(quota.used)+' / '+number(quota.limit) : error"><span>{{ name.slice(0,1) }}</span></span>{{name}}</button>
<div v-if="menu" class="menu"><b>{{store.user?.username}}</b><span v-if="quota">本月 Token 已用 {{number(quota.used)}} / {{number(quota.limit)}}</span><span v-else>{{error || '正在读取额度'}}</span><button @click="menu=false; openChatbotChooser()">切换业务助手</button><button @click="menu=false; logout()">退出登录</button></div></div></header></template>
<style scoped>
.accountbar{height:56px;flex:0 0 56px;padding:0 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line,#e7e7ec);background:var(--surface,#fff);z-index:14;color:var(--ink)}
nav,.profile,.user,nav a{display:flex;align-items:center;gap:8px}nav a,.gear,.user{color:var(--ink-2);text-decoration:none;padding:8px 12px;border-radius:8px;font-size:14px;font-weight:600}.gear{display:grid;place-items:center}svg{width:17px;height:17px}.active{background:#fff0f4;color:var(--accent,#c90040)}button{cursor:pointer;font:inherit;background:none;border:0}.profile{position:relative}.ring{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent,#c90040) var(--usage),#dedde5 0)}.ring>span{background:white;border-radius:50%;width:23px;height:23px;display:grid;place-items:center;color:var(--accent);font-size:12px}.menu{position:absolute;right:0;top:calc(100% + 4px);width:max-content;max-width:80vw;background:white;border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 25px #15152116;display:grid;gap:8px;padding:16px}.menu span{font-size:12px}.menu button{text-align:left;padding:6px 0}
@media (max-width: 620px) {
  .accountbar { padding-inline: 8px; }
  nav, .profile, nav a { gap: 4px; }
  nav a, .gear, .user { padding-inline: 6px; }
  .user { max-width: 130px; overflow: hidden; white-space: nowrap; }
}
</style>
