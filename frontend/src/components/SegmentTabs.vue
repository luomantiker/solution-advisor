<script setup lang="ts">
import SidebarIcon from './SidebarIcon.vue'
defineProps<{ items: Array<{ id: string; label: string; icon?: 'platform' | 'settings' | 'report' | 'model' }>; modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template><nav class="segment-tabs" aria-label="页面分区"><button v-for="item in items" :key="item.id" type="button" :class="{ active: item.id === modelValue }" @click="$emit('update:modelValue', item.id)"><SidebarIcon v-if="item.icon" :name="item.icon"/><span>{{ item.label }}</span></button></nav></template>
