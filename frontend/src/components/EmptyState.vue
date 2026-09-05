<script setup lang="ts">
defineProps<{ icon?: string; title: string; description: string }>()
</script>

<template><div class="empty-state"><span aria-hidden="true">{{ icon || '○' }}</span><strong>{{ title }}</strong><p>{{ description }}</p><slot /></div></template>
