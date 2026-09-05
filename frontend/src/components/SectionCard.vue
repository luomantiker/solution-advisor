<script setup lang="ts">
defineProps<{ title?: string; description?: string }>()
</script>

<template>
  <section class="section-card">
    <header v-if="title || $slots.actions" class="section-card-header"><div><h3 v-if="title">{{ title }}</h3><p v-if="description">{{ description }}</p></div><div><slot name="actions" /></div></header>
    <slot />
  </section>
</template>
