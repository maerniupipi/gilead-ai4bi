<script setup>
defineProps({
  name: { type: String, required: true },
})
</script>

<template>
  <svg class="nav-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <g v-if="name === 'grid'" stroke="currentColor" stroke-width="1.6"><rect x="4" y="4" width="7" height="7" rx="2"/><rect x="14" y="4" width="6" height="11" rx="2"/><rect x="4" y="14" width="7" height="6" rx="2"/><path d="M14 18h6" stroke-linecap="round"/></g>
    <g v-else-if="name === 'chat'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6.5 6.2h11c1.3 0 2.3 1 2.3 2.3v6.1c0 1.3-1 2.3-2.3 2.3h-5.1L8.2 20.2v-3.3H6.5c-1.3 0-2.3-1-2.3-2.3V8.5c0-1.3 1-2.3 2.3-2.3Z" />
      <path d="M9 10.4h6.2M9 13.3h4" />
    </g>
    <g v-else-if="name === 'memory'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M7.2 4.6h9.6c.8 0 1.4.6 1.4 1.4V19l-6.2-3.1L5.8 19V6c0-.8.6-1.4 1.4-1.4Z" />
    </g>
    <g v-else-if="name === 'knowledge'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5.4 6.2c0-1 .8-1.8 1.8-1.8H19v14.2H7.2c-1 0-1.8-.8-1.8-1.8V6.2Z" />
      <path d="M5.4 16.8c0-1 .8-1.8 1.8-1.8H19" />
      <path d="M9.2 7.8h6.4M9.2 11h4.6" />
    </g>
    <g v-else-if="name === 'trace'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3.8 12.5h3.4l2.4-6.2 4.2 11.4 2.3-5.2h4.1" />
    </g>
    <g v-else-if="name === 'admin'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="m9 3-.6 2a7 7 0 0 0-1.8 1L4.6 5.5 2.9 8.4l1.5 1.5a7.5 7.5 0 0 0 0 2.2l-1.5 1.6 1.7 3 2-.6a7 7 0 0 0 1.8 1l.6 2h3.5l.6-2a7 7 0 0 0 1.8-1l2 .6 1.7-3-1.5-1.6a7.5 7.5 0 0 0 0-2.2l1.5-1.5-1.7-2.9-2 .5a7 7 0 0 0-1.8-1l-.6-2Z" transform="translate(1.2 1)"/>
      <circle cx="12" cy="12" r="3"/>
    </g>
    <g v-else-if="name === 'review'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="7.4" />
      <path d="m8.8 12.2 2.1 2.1 4.4-4.6" />
    </g>
    <g v-else-if="name === 'source'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <ellipse cx="12" cy="7" rx="6.4" ry="2.4" />
      <path d="M5.6 7v5c0 1.3 2.9 2.4 6.4 2.4s6.4-1.1 6.4-2.4V7" />
      <path d="M5.6 12v5c0 1.3 2.9 2.4 6.4 2.4s6.4-1.1 6.4-2.4v-5" />
    </g>
    <g v-else-if="name === 'agent'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="7.2" cy="8.2" r="2.4" />
      <circle cx="16.8" cy="8.2" r="2.4" />
      <circle cx="12" cy="16.4" r="2.4" />
      <path d="M9.2 9.4 10.6 14.2M14.8 9.4 13.4 14.2" />
    </g>
    <g v-else-if="name === 'lab'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9 4h6M10 4v6l-5.3 8.2A1.2 1.2 0 0 0 5.7 20h12.6a1.2 1.2 0 0 0 1-1.8L14 10V4M8.2 13.5h7.6" />
      <path d="M10 16.5h.01M14 17.5h.01" />
    </g>
    <g v-else-if="name === 'tool'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14.8 5.2 9.4 10.6l4 4 5.4-5.4" />
      <path d="M8.6 11.4 4.8 18.4l2.2.8.8 2.2 7-3.8" />
      <path d="M16.4 4.2c1.4-1.4 3.6-1.5 4.8-.3s1.1 3.4-.3 4.8" />
    </g>
    <g v-else-if="name === 'pack'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 4.6 19.2 8v8L12 19.4 4.8 16V8L12 4.6Z" />
      <path d="M12 19.4V12M19.2 8 12 12 4.8 8" />
    </g>
    <g v-else-if="name === 'brand'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="8.2" cy="9.2" r="3.2" />
      <circle cx="15.6" cy="8.2" r="2.4" />
      <circle cx="13.4" cy="15.4" r="2.8" />
    </g>
    <g v-else-if="name === 'users'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="9" cy="8.2" r="2.6" />
      <path d="M4.6 17.2c.4-2.6 2.2-4 4.4-4s4 1.4 4.4 4" />
      <circle cx="16.2" cy="8.8" r="2.1" />
      <path d="M14.2 17.2c.3-1.8 1.5-3 3.2-3 1.2 0 2.2.6 2.8 1.6" />
    </g>
    <g v-else-if="name === 'model'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <rect x="5.4" y="5.4" width="13.2" height="13.2" rx="3" />
      <path d="M9.2 3.8v1.6M14.8 3.8v1.6M9.2 18.6v1.6M14.8 18.6v1.6M3.8 9.2h1.6M3.8 14.8h1.6M18.6 9.2h1.6M18.6 14.8h1.6" />
    </g>
    <g v-else-if="name === 'eval'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <rect x="5.2" y="4.6" width="13.6" height="14.8" rx="2.2" />
      <path d="M8.2 9h7.6M8.2 12.2h7.6M8.2 15.4h4.8" />
    </g>
    <g v-else-if="name === 'usage'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5.2 17.6V6.4M10.2 17.6V10.2M15.2 17.6V8.4M19.8 17.6V4.8" />
      <path d="M4.4 17.6h16" />
    </g>
    <g v-else-if="name === 'ops'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <rect x="4.6" y="5.2" width="14.8" height="13.6" rx="2.2" />
      <path d="M8 9.2h8M8 12.2h8M8 15.2h5" />
      <path d="m15.6 14.6 1.4 1.4 2.4-2.6" />
    </g>
    <g v-else-if="name === 'plus'" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M12 6.4v11.2M6.4 12h11.2" />
    </g>
    <g v-else-if="name === 'logout'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10 6.2H7.4A1.8 1.8 0 0 0 5.6 8v8A1.8 1.8 0 0 0 7.4 17.8H10" />
      <path d="M10.8 12h7.6M15.6 8.8 18.8 12l-3.2 3.2" />
    </g>
    <g v-else-if="name === 'chevron'" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="m9 7.2 5.2 4.8L9 16.8" />
    </g>
  </svg>
</template>
