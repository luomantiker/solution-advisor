<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, upload } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import ActionIcon from '../components/ActionIcon.vue'
const router = useRouter(); const error = ref(''); const selectedFile = ref<File>(); const uploading = ref(false); const stage = ref('')
function selectFile(event: Event) { const input = event.target as HTMLInputElement; selectedFile.value = input.files?.[0]; error.value = ''; stage.value = '' }
function readableError(cause: unknown) { return cause instanceof Error ? cause.message : '上传或分析请求未完成，请重试。' }
async function submit(event: Event) {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true; error.value = ''; stage.value = '正在上传模型…'
  try {
    const form = new FormData(); form.set('file', selectedFile.value)
    const data = await upload(form); const id = data.analysis_task.id; stage.value = '上传完成，正在生成 Model Profile…'
    const poll = async (): Promise<void> => { const task = await api(`/analysis-tasks/${id}`); if (task.status === 'SUCCEEDED') return router.push(`/models/${data.asset.id}`); if (task.status === 'FAILED') throw new Error('通用 ONNX 分析失败，请查看任务详情或联系管理员。'); await new Promise(r => setTimeout(r, 500)); return poll() }
    await poll()
  } catch (cause) { error.value = readableError(cause); stage.value = '' } finally { uploading.value = false }
}
</script>
<template><section class="page"><PageHeader title="上传模型" description="上传 ONNX 后，系统会自动分析模型结构；分析完成后即可选择平台创建评估。" eyebrow="我的模型"/><SectionCard title="选择 ONNX 文件" description="选择文件后会立即显示名称。您不需要填写命令、路径或板卡信息，系统会统一处理。"><form class="upload-form" @submit.prevent="submit"><label class="file-picker">选择文件 <input name="file" type="file" accept=".onnx" required @change="selectFile"></label><div v-if="selectedFile" class="selected-file"><strong>{{ selectedFile.name }}</strong><small>{{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB · 已选择</small></div><button class="button-primary" :disabled="!selectedFile || uploading"><ActionIcon name="upload"/>{{ uploading ? '正在上传并分析…' : '上传并分析' }}</button></form><p v-if="stage" class="feedback">{{ stage }}</p><p v-if="error" class="feedback error">{{ error }}</p></SectionCard></section></template>
