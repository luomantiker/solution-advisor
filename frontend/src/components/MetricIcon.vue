<script setup lang="ts">
defineProps<{ kind: string }>()
</script>

<template>
  <svg v-if="kind==='◐'" class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4a8 8 0 1 0 8 8h-8V4Z" fill="currentColor" opacity=".18"/><path d="M12 4a8 8 0 0 1 8 8h-8V4Z" fill="currentColor"/><path d="M12 4v8h8" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
  <svg v-else-if="kind==='●'||kind==='✓'" class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.8"/><path d="m8.4 12.1 2.35 2.35 4.9-5.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
  <svg v-else-if="kind==='▦'" class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" stroke="currentColor" stroke-width="1.8"/><path d="M8 8h2.5v2.5H8zM13.5 8H16v2.5h-2.5zM8 13.5h2.5V16H8zM13.5 13.5H16V16h-2.5z" fill="currentColor"/></svg>
  <svg v-else-if="kind==='▤'" class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 3.8h7l3.2 3.2v12.2A1.8 1.8 0 0 1 15.4 21H7a1.8 1.8 0 0 1-1.8-1.8V5.6A1.8 1.8 0 0 1 7 3.8Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3.8V7h3.2M8.5 11h7M8.5 14.5h7M8.5 18h4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
  <svg v-else-if="kind==='♙'" class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.2" stroke="currentColor" stroke-width="1.8"/><path d="M5.7 19.5c.6-3.1 2.7-4.8 6.3-4.8s5.7 1.7 6.3 4.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
  <svg v-else class="metric-svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="7.8" stroke="currentColor" stroke-width="1.8"/><path d="M12 8v4.2l2.8 1.7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
</template>
