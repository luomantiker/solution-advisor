<script setup lang="ts">
defineProps<{ name: 'home' | 'upload' | 'model' | 'report' | 'platform' | 'people' | 'settings' | 'notification' | 'help' | 'collapse' }>()
</script>

<template>
  <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name === 'home'"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z" /></template>
    <template v-else-if="name === 'upload'"><path d="M12 16V3M7 8l5-5 5 5M5 21h14" /></template>
    <template v-else-if="name === 'model'"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 16v-3m4 3V9m4 7v-5m4 5v-2" /></template>
    <template v-else-if="name === 'report'"><path d="M6 3h9l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" /><path d="M14 3v5h5M8 13h8M8 17h6" /></template>
    <template v-else-if="name === 'platform'"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 8h10M7 12h4m2 0h4M7 16h10" /></template>
    <template v-else-if="name === 'people'"><circle cx="9" cy="8" r="3" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0M17 11a3 3 0 1 0-1.2-5.75M16 15.5a5.5 5.5 0 0 1 4.5 4.5" /></template>
    <template v-else-if="name === 'settings'"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.28 2.28-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.5h-3.22v-.12A1.7 1.7 0 0 0 10.3 18.8a1.7 1.7 0 0 0-1.88.34l-.06.06-2.28-2.28.06-.06A1.7 1.7 0 0 0 6.48 15a1.7 1.7 0 0 0-1.56-1.03H4.8v-3.22h.12A1.7 1.7 0 0 0 6.48 9.7a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.28-2.28.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56V4.2h3.22v.12A1.7 1.7 0 0 0 15.58 5.9a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.28 2.28-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.12v3.22h-.12A1.7 1.7 0 0 0 19.4 15Z" /></template>
    <template v-else-if="name === 'notification'"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></template>
    <template v-else-if="name === 'help'"><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.6 2.6 0 1 1 4.2 2.1c-1.2.9-1.7 1.4-1.7 2.9M12 17h.01" /></template>
    <template v-else><path d="M19 12H5m6-6-6 6 6 6" /></template>
  </svg>
</template>
