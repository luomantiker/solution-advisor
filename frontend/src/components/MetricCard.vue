<script setup lang="ts">
import MetricIcon from './MetricIcon.vue'
defineProps<{ icon: string; label: string; value: string | number; description: string; tone?: 'neutral'|'progress'|'success'|'warning'|'danger' }>()
</script>

<template>
  <article class="metric-card" :class="`tone-${tone || 'neutral'}`">
    <span class="metric-icon" aria-hidden="true"><MetricIcon :kind="icon" /></span>
    <div><span class="metric-label">{{ label }}</span><strong>{{ value }}</strong><small>{{ description }}</small></div>
  </article>
</template>
