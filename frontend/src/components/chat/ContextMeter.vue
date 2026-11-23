<script setup>
import { computed, ref } from 'vue'
import { tokenNumber } from '../../context.js'

const props = defineProps({ reading: { type: Object, required: true } })
const open = ref(false)
const available = computed(() => Number.isFinite(props.reading.used))
const fraction = computed(() => available.value ? Math.min(1, props.reading.used / props.reading.limit) : 0)
const percent = computed(() => (fraction.value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 }))
const threshold = computed(() => Math.round(props.reading.threshold / props.reading.limit * 100))
const label = computed(() => available.value
  ? `当前上下文 ${tokenNumber(props.reading.used)} / ${tokenNumber(props.reading.limit)} Token，占用 ${percent.value}%`
  : '当前上下文尚无用量记录')
</script>

<template>
  <div class="context-meter" :class="{ nearing: fraction >= threshold / 100 }">
    <button type="button" class="context-trigger" :aria-label="label" :aria-expanded="open"
      @click="open = !open" @blur="open = false" @keydown.esc="open = false">
      <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
        <circle cx="12" cy="12" r="9" class="track" />
        <circle v-if="fraction" cx="12" cy="12" r="9" pathLength="100" class="fill"
          :stroke-dasharray="`${fraction * 100} 100`" transform="rotate(-90 12 12)" />
        <path d="M12 1v3" :transform="`rotate(${threshold * 3.6} 12 12)`" class="marker" />
      </svg>
      <span>上下文</span>
      <span class="counts">{{ available && reading.source && reading.source !== 'provider' ? '约 ' : '' }}{{ available ? tokenNumber(reading.used) : '—' }} / {{ tokenNumber(reading.limit) }} Token</span>
      <span class="percent">{{ available ? percent + '%' : '' }}</span>
    </button>
    <div v-if="open" class="context-detail">
      <strong>会话上下文</strong>
      <span>{{ label }}</span>
      <span>达到 {{ threshold }}%（{{ tokenNumber(reading.threshold) }} Token）时自动压缩。</span>
      <span>保留当前问题、筛选条件和关键结果。原始问答可在会话记录中查看。</span>
    </div>
  </div>
</template>

<style scoped>
.context-meter { position: relative; color: var(--ink-2, #555865); font-size: 11px; }
.context-trigger { display: inline-flex; align-items: center; gap: 5px; padding: 3px 5px; background: transparent; border: 0; border-radius: 5px; color: inherit; font: inherit; cursor: pointer; }
.context-trigger:hover, .context-trigger:focus-visible { background: var(--surface-2, #f3f3f6); }
.context-trigger:focus-visible { outline: 2px solid var(--accent, #c90042); }
svg { flex: none; fill: none; stroke-width: 2.5; }
.track { stroke: #dbdce3; }
.fill { stroke: var(--accent, #bd1746); }
.marker { stroke: #676a78; stroke-width: 1.5; }
.counts, .percent { font-variant-numeric: tabular-nums; white-space: nowrap; }
.percent { color: var(--ink-2, #555865); }
.nearing .percent { color: #9b520c; font-weight: 650; }
.context-detail { position: absolute; bottom: calc(100% + 8px); left: 0; width: min(270px, 80vw); z-index: 4; display: grid; gap: 5px; text-align: left; padding: 12px 14px; font-size: 12px; line-height: 1.5; border: 1px solid #dddde5; border-radius: 9px; background: white; box-shadow: 0 4px 15px #25293814; }
.context-detail strong { color: var(--ink, #252938); }
</style>
