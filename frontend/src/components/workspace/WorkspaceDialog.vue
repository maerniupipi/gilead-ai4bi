<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import '../../styles/workspace.css'
const props = defineProps({ title: { type: String, required: true }, subtitle: { type: String, default: '' }, busy: Boolean })
const emit = defineEmits(['close'])
const panel = ref(null)
const titleId = `workspace-dialog-${Math.random().toString(36).slice(2)}`
let previousFocus
function close() { if (!props.busy) emit('close') }
function keydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key !== 'Tab') return
  const focusable = [...panel.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select,textarea,a[href],[tabindex="0"]')].filter(el => el.offsetParent !== null)
  const first = focusable[0], last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(async () => {
  previousFocus = document.activeElement
  document.addEventListener('keydown', keydown)
  await nextTick()
  panel.value.querySelector('input,button')?.focus()
})
onBeforeUnmount(() => { document.removeEventListener('keydown', keydown); previousFocus?.focus?.() })
</script>
<template>
  <Teleport to="body"><div class="ws-veil" @click.self="close"><section ref="panel" class="ws-dialog" role="dialog" aria-modal="true" :aria-labelledby="titleId"><header class="ws-dialog-head"><div><span>GILEAD · WORKSPACE</span><h2 :id="titleId">{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div><button type="button" class="ws-close" aria-label="关闭弹窗" :disabled="busy" @click="close">×</button></header><slot /></section></div></Teleport>
</template>
