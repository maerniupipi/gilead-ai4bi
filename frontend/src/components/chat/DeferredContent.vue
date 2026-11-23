<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { deferRender } from '../../utils/rendering.js'

const props = defineProps({
  defer: { type: Boolean, default: true },
  pending: { type: Boolean, default: false },
  label: { type: String, default: '内容正在渲染…' },
  minHeight: { type: Number, default: 280 },
})
const host = ref(null)
const ready = ref(!props.defer && !props.pending)
let active = !props.defer
let observer = null
let cancelWork = () => {}

function renderWhenReady() {
  cancelWork()
  if (ready.value || !active || props.pending) return
  cancelWork = deferRender(() => {
    if (!active || props.pending) return
    ready.value = true
    observer?.disconnect()
  })
}

onMounted(() => {
  if (!props.defer || !globalThis.IntersectionObserver) {
    active = true
    renderWhenReady()
    return
  }
  observer = new IntersectionObserver(entries => {
    active = entries.some(entry => entry.isIntersecting)
    renderWhenReady()
  }, { root: host.value.closest('.chat'), rootMargin: '0px' })
  observer.observe(host.value)
})
watch(() => props.pending, renderWhenReady)
onBeforeUnmount(() => { cancelWork(); observer?.disconnect() })
</script>

<template>
  <div ref="host" class="deferred-content" :aria-busy="!ready">
    <slot v-if="ready"></slot>
    <div v-else class="render-placeholder" :style="{ minHeight: `${minHeight}px` }" role="status">
      <p><i aria-hidden="true"></i>{{ pending ? '历史内容正在加载…' : label }}</p>
      <div class="render-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>
    </div>
  </div>
</template>

<style scoped>
.deferred-content { min-width: 0; }
.render-placeholder { box-sizing: border-box; padding: 24px; margin: 12px 0; border: 1px solid var(--line); border-radius: 14px; background: var(--paper); overflow-anchor: none; }
.render-placeholder p { display: flex; align-items: center; gap: 9px; margin: 0 0 22px; font-size: 12px; color: var(--ink-2); }
.render-placeholder i { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
.render-skeleton { display: grid; gap: 13px; }
.render-skeleton span { display: block; height: 11px; max-width: 92%; border-radius: 4px; background: var(--bg); }
.render-skeleton span:nth-child(2) { max-width: 78%; }
.render-skeleton span:nth-child(3) { max-width: 58%; }
@keyframes pulse { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .render-placeholder i { animation: none; } }
</style>
