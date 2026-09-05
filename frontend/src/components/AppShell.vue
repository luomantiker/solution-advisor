<script setup lang="ts">
defineProps<{ collapsed: boolean }>()
</script>

<template><div class="app-shell" :class="{ 'sidebar-collapsed': collapsed }"><aside class="sidebar" aria-label="主导航"><slot name="sidebar" /></aside><main class="content-canvas"><div class="content-title-region"><slot name="header" /></div><div class="content-body"><slot /></div></main><slot name="overlays" /></div></template>
