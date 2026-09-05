<script setup lang="ts">
defineProps<{ tone?: 'neutral'|'progress'|'success'|'warning'|'danger' }>()
</script>

<template><span class="status-badge" :class="`tone-${tone || 'neutral'}`"><slot /></span></template>
