<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/backend.js'
import { showToast } from '../store.js'
const endpoint = ref(''), token = ref(''), pairs = ref([]), configured = ref(false), busy = ref(false), error = ref('')
function apply(data) { endpoint.value = data.endpoint_url; pairs.value = data.pairs; configured.value = data.configured; token.value = '' }
onMounted(async () => { try { apply(await api.labPairs()) } catch (e) { error.value = e.message } })
function add() { pairs.value.push({ id:'', name:'', recall:'', sql:'' }) }
async function save() {
  busy.value=true; error.value=''
  try { apply(await api.saveLabPairs({ endpoint_url:endpoint.value, authorization:token.value || null, pairs:pairs.value })); showToast('实验室连接已保存') }
  catch(e) { error.value=e.message } finally { busy.value=false }
}
</script>
<template><main class="pair-page"><header><h1>实验室连接</h1><p>吉利德AI平台</p></header>
<form @submit.prevent="save">
  <section><h2>平台连接</h2><label>服务地址<input v-model.trim="endpoint" required type="url" /></label>
  <label>服务密钥<input v-model.trim="token" autocomplete="new-password" type="password" :placeholder="configured ? '已配置，留空可继续使用' : '输入服务密钥'" /></label></section>
  <section><div class="row"><h2>实验室组合</h2><button type="button" @click="add">添加组合</button></div>
  <fieldset v-for="(pair,i) in pairs" :key="i"><legend>{{ pair.name || '新组合' }}</legend><div class="fields">
  <label>组合编号<input v-model.trim="pair.id" pattern="[a-zA-Z0-9_\-]{1,48}" required /></label><label>名称<input v-model.trim="pair.name" required /></label>
  <label>召回实验室调用 ID<input v-model.trim="pair.recall" pattern="[a-zA-Z0-9]{10}" required /></label>
  <label>SQL 实验室调用 ID<input v-model.trim="pair.sql" pattern="[a-zA-Z0-9]{10}" required /></label></div>
  <button type="button" v-if="pairs.length>1" @click="pairs.splice(i,1)">移除此组合</button></fieldset></section>
  <p v-if="error" role="alert">{{ error }}</p><button class="save" :disabled="busy || !pairs.length">保存配置</button>
</form></main></template>
<style scoped>
.pair-page{width:min(850px,100%);margin:0 auto;padding:32px;overflow:auto;color:var(--ink)}
h1{font-size:28px;margin:0}header p,label{color:var(--ink-2)}section{background:var(--surface,#fff);border:1px solid var(--line,#ddd);border-radius:14px;padding:22px;margin:18px 0}
h2{font-size:16px;margin:0 0 12px}.row,.fields{display:flex;gap:16px;align-items:center}.row{justify-content:space-between}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
label{display:grid;gap:6px;margin:10px 0;font-size:13px}input,button{font:inherit;border-radius:8px;padding:9px 12px;border:1px solid var(--line,#ddd);background:white}button{cursor:pointer}.save{background:var(--accent,#c80040);color:white}fieldset{border:1px solid var(--line,#ddd);border-radius:8px;margin-top:12px}legend{padding:0 5px;font-weight:650}p[role=alert]{color:#a91d41}
</style>