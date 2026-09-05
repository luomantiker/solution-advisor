<script setup lang="ts">
defineProps<{ open: boolean; title: string; description: string; confirmLabel?: string }>()
defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template><Teleport to="body"><div v-if="open" class="modal-backdrop"><section class="modal confirm-dialog" role="dialog" aria-modal="true"><h2>{{ title }}</h2><p>{{ description }}</p><footer><button type="button" @click="$emit('cancel')">取消</button><button type="button" class="button-danger" @click="$emit('confirm')">{{ confirmLabel || '确认执行' }}</button></footer></section></div></Teleport></template>
