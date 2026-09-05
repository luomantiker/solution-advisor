<script setup lang="ts">
defineProps<{ open: boolean; title: string }>()
defineEmits<{ close: [] }>()
</script>

<template><Teleport to="body"><div v-if="open" class="side-panel-backdrop" @click.self="$emit('close')"><aside class="side-panel" role="dialog" aria-modal="true"><header><div><p class="eyebrow">详细信息</p><h2>{{ title }}</h2></div><button type="button" aria-label="关闭详情" @click="$emit('close')">×</button></header><div class="side-panel-body"><slot /></div></aside></div></Teleport></template>
