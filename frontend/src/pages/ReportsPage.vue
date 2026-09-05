<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import ActionIcon from '../components/ActionIcon.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
const data=ref<any>(), error=ref(''), deleting=ref<any>()
const text=(v:string)=>({SUCCEEDED:'成功',PARTIALLY_SUCCEEDED:'部分成功',FAILED:'失败',CANCELLED:'已取消',TIMEOUT:'超时'} as Record<string,string>)[v]||v
const tone=(v:string)=>v==='SUCCEEDED'?'success':v==='PARTIALLY_SUCCEEDED'?'progress':v==='FAILED'?'danger':'warning'
function save(value:Blob, filename:string){const url=URL.createObjectURL(value);const a=document.createElement('a');a.href=url;a.download=filename;a.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function pdf(flow:any){try{save(await api(`/evaluation-flows/${flow.id}/report/download`) as Blob,`${flow.id}-报告.pdf`)}catch(cause){error.value=cause instanceof Error?cause.message:'PDF 下载失败。'}}
async function load(){try{data.value=await api('/evaluation-workbench')}catch(cause){error.value=cause instanceof Error?cause.message:'报告中心加载失败。'}}
async function removeFlow(){if(!deleting.value)return;try{await api(`/evaluation-flows/${deleting.value.id}`,{method:'DELETE'});deleting.value=undefined;await load()}catch(cause){error.value=cause instanceof Error?cause.message:'删除评估失败。'}}
onMounted(load)
</script>
<template><section class="page reports-page"><PageHeader title="我的报告" description="每一份报告对应一次完整评估，您可以在线查看结果或下载 PDF 留存。" eyebrow="评估报告"/><p v-if="error" class="feedback error">{{error}}</p><SectionCard title="报告中心" description="打开网页预览可查看本次评估详情；PDF 与网页报告展示同一份评估结果。"><EmptyState v-if="data&&!data.recent_reports.length" icon="▤" title="暂无报告" description="完成一次评估后，报告会自动显示在这里，您可随时查看或下载。"/><div v-else-if="data" class="table-wrap"><table class="data-table"><thead><tr><th>报告 / 模型</th><th>平台</th><th>结论</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="flow in data.recent_reports" :key="flow.id"><td><strong>{{flow.model_name}}</strong><small>{{flow.id}}</small></td><td>{{flow.platforms.join(' + ')}}</td><td><StatusBadge :tone="tone(flow.status)">{{text(flow.status)}}</StatusBadge></td><td>{{flow.created_at||'未记录'}}</td><td class="table-actions"><div class="table-action-group"><RouterLink class="row-secondary-action" :to="`/flows/${flow.id}`"><ActionIcon name="report"/>查看报告</RouterLink><button class="row-primary-action" @click="pdf(flow)"><ActionIcon name="download"/>下载 PDF</button><button class="row-danger-action" @click="deleting=flow"><ActionIcon name="delete"/>删除评估</button></div></td></tr></tbody></table></div><p v-else class="muted">正在加载报告中心…</p></SectionCard><ConfirmDialog :open="Boolean(deleting)" title="删除本次评估" description="将删除这次评估的内部阶段、专属 Evidence、网页报告和 PDF；不会删除模型或其它评估。此操作无法恢复。" confirm-label="确认删除" @cancel="deleting=undefined" @confirm="removeFlow" /></section></template>
