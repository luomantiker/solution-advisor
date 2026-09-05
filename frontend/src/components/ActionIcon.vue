<script setup lang="ts">
defineProps<{ name: 'report' | 'download' | 'delete' | 'create' | 'view' | 'model' | 'upload' | 'refresh' | 'edit' | 'lock' | 'unlock' | 'save' | 'check' | 'clear' }>()
</script>

<template>
  <svg class="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name==='report'"><path d="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v5h5M8 13h8M8 17h5"/></template>
    <template v-else-if="name==='download'"><path d="M12 3v12M7.5 10.5 12 15l4.5-4.5M5 21h14"/></template>
    <template v-else-if="name==='create'"><path d="M12 5v14M5 12h14"/><circle cx="12" cy="12" r="9"/></template>
    <template v-else-if="name==='view'"><path d="M2.5 12s3.4-5.5 9.5-5.5S21.5 12 21.5 12 18.1 17.5 12 17.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.5"/></template>
    <template v-else-if="name==='model'"><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5M8 14h8M8 18h6"/></template>
    <template v-else-if="name==='upload'"><path d="M12 16V3M7.5 7.5 12 3l4.5 4.5M5 15v5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5"/></template>
    <template v-else-if="name==='refresh'"><path d="M20 11a8 8 0 1 0 1.3 4.4"/><path d="M20 5v6h-6"/></template>
    <template v-else-if="name==='edit'"><path d="m4 16-.8 4.8L8 20l10.7-10.7a2.2 2.2 0 0 0-3.1-3.1L4.9 16Z"/><path d="m13.8 8.1 3.1 3.1"/></template>
    <template v-else-if="name==='lock'"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></template>
    <template v-else-if="name==='unlock'"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.4-1.8M12 14v3"/></template>
    <template v-else-if="name==='save'"><path d="M5 3h12l3 3v15H5z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/></template>
    <template v-else-if="name==='check'"><path d="m5 12 4.2 4.2L19 6.5"/></template>
    <template v-else-if="name==='clear'"><path d="m6 6 12 12M18 6 6 18"/></template>
    <template v-else><path d="M4 7h16M10 11v6M14 11v6M9 7l1-3h4l1 3M6 7l.8 14h10.4L18 7"/></template>
  </svg>
</template>
