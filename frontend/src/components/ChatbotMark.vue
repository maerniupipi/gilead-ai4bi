<script setup>
defineProps({ category: { type: String, default: 'general' } })
</script>

<template>
  <span class="bot-mark" :class="category" aria-hidden="true">
    <svg viewBox="0 0 32 32" fill="none">
      <g v-if="category === 'ddi'" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
        <path d="M7 23V16M16 23V10M25 23V5" /><path d="m6 11 9-6 7 1" opacity=".42" />
      </g>
      <g v-else-if="category === 'behavior'" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 7h24l-5 7H9L4 7ZM10 18h12l-4 7h-4l-4-7Z" /><path d="m14 10 2 2 3-3" opacity=".65" />
      </g>
      <g v-else stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><rect x="5" y="5" width="22" height="22" rx="7" /><path d="M11 12h10M11 17h7M11 22h3" stroke-linecap="round" /></g>
    </svg>
  </span>
</template>

<style scoped>
.bot-mark{display:inline-flex;align-items:center;justify-content:center;flex:none;width:52px;height:52px;border-radius:17px;background:#fbecef;color:#c5203f;border:1px solid #f3dce1}.bot-mark.behavior{background:#eaf3f5;color:#206778;border-color:#d8e9ed}.bot-mark.general{background:#f0edf7;color:#66577f;border-color:#e4dfef}.bot-mark svg{width:31px;height:31px}
</style>
