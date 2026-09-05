<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import ActionIcon from '../components/ActionIcon.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const route=useRoute();const model=ref<any>();const flows=ref<any[]>([]);const platforms=ref<any[]>([]);const error=ref('');const deletingFlow=ref<any>()
const canCreate=computed(()=>Boolean(model.value?.profile&&model.value?.can_create_task))
const summary=computed(()=>model.value?.profile?.summary||{})
const flags=computed(()=>summary.value.structure_flags||{})
const operators=computed(()=>Object.entries(summary.value.operator_counts||{}).sort((a:any,b:any)=>Number(b[1])-Number(a[1])))
const ioRows=computed(()=>[
  ...(summary.value.inputs||[]).map((item:any)=>({kind:'输入',...item})),
  ...(summary.value.outputs||[]).map((item:any)=>({kind:'输出',...item})),
])
const totalOperators=computed(()=>operators.value.reduce((sum:number,[,count]:any)=>sum+Number(count),0))
const state=(v:string)=>({SUCCEEDED:'成功',PARTIALLY_SUCCEEDED:'部分成功',FAILED:'失败',CANCELLED:'已取消',TIMEOUT:'超时',RUNNING:'执行中',QUEUED:'等待执行'} as Record<string,string>)[v]||v
const tone=(v:string)=>v==='SUCCEEDED'?'success':v==='PARTIALLY_SUCCEEDED'||v==='RUNNING'?'progress':v==='QUEUED'?'warning':'danger'
const size=(value?:number)=>{if(value===undefined||value===null)return'未记录';if(value<1024)return `${value} 字节`;if(value<1024**2)return `${(value/1024).toFixed(1)} KB`;return `${(value/1024**2).toFixed(2)} MB`}
const time=(value?:string)=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'未记录'
const opset=computed(()=>{const values=summary.value.opset_imports||[];return values.map((item:any)=>`${item.domain||'ai.onnx'} ${item.version}`).join('；')||'未记录'})
function shape(value:any){return Array.isArray(value)?`[${value.map(item=>item??'?').join(', ')}]`:'未记录'}
function save(value:Blob, name:string){const u=URL.createObjectURL(value),a=document.createElement('a');a.href=u;a.download=name;a.click();window.setTimeout(()=>URL.revokeObjectURL(u),1000)}
async function download(){try{save(await api(`/model-assets/${route.params.assetId}/download`) as Blob,model.value.original_filename)}catch(cause){error.value=cause instanceof Error?cause.message:'模型下载失败。'}}
async function pdf(flow:any){try{save(await api(`/evaluation-flows/${flow.id}/report/download`) as Blob,`${flow.id}-报告.pdf`)}catch(cause){error.value=cause instanceof Error?cause.message:'PDF 下载失败。'}}
async function removeFlow(){if(!deletingFlow.value)return;try{await api(`/evaluation-flows/${deletingFlow.value.id}`,{method:'DELETE'});deletingFlow.value=undefined;await load()}catch(cause){error.value=cause instanceof Error?cause.message:'删除评估失败。'}}
async function load(){try{model.value=await api(`/model-assets/${route.params.assetId}`);flows.value=(await api(`/model-assets/${route.params.assetId}/evaluation-tasks`) as any[]).filter(item=>item.resource_kind==='FLOW');platforms.value=await api('/evaluation-platforms')}catch(cause){error.value=cause instanceof Error?cause.message:'模型详情加载失败。'}}
onMounted(load)
</script>

<template>
  <section v-if="model" class="page model-detail-page">
    <PageHeader :title="model.original_filename" description="查看模型资产、结构分析、可评估平台和该模型的历史评测结果。" eyebrow="模型资产" />
    <p v-if="error" class="feedback error">{{error}}</p>

    <SectionCard title="模型资产概览" description="模型文件和分析快照均按当前访问权限展示；下载时由后端再次校验授权。">
      <div class="asset-overview">
        <div class="asset-title"><span class="asset-file-icon"><ActionIcon name="model" /></span><div><strong>{{model.original_filename}}</strong><small>ONNX 模型 · {{size(model.size_bytes)}}</small></div></div>
        <div class="asset-fact"><small>文件标识</small><code title="SHA256">{{model.sha256}}</code></div>
        <div class="asset-fact"><small>上传时间</small><strong>{{time(model.created_at)}}</strong></div>
        <div class="asset-fact"><small>访问范围</small><StatusBadge :tone="model.access==='OWNER'?'success':'neutral'">{{model.access==='OWNER'?'我上传':'获授权访问'}}</StatusBadge></div>
      </div>
      <div class="detail-actions"><button v-if="model.can_download_model" class="button-secondary" @click="download"><ActionIcon name="download" />下载模型</button><RouterLink v-if="canCreate" class="button-primary" :to="`/tasks/new?profile_id=${model.profile.id}`"><ActionIcon name="create" />创建评估</RouterLink></div>
    </SectionCard>

    <SectionCard v-if="model.profile" title="通用 ONNX 结构分析" description="此处确认模型文件的通用结构事实；平台支持、编译和板端性能仍需通过独立评测验证。">
      <div class="analysis-metrics">
        <div><span>▦</span><small>节点数量</small><strong>{{summary.node_count??'未记录'}}</strong></div>
        <div><span>⌘</span><small>算子类别</small><strong>{{summary.operator_type_count??operators.length}}</strong></div>
        <div><span>◫</span><small>算子总数</small><strong>{{totalOperators||'未记录'}}</strong></div>
      </div>
      <div class="analysis-detail-grid">
        <article><small>ONNX 版本信息</small><strong>IR {{summary.ir_version??'未记录'}} · Opset {{opset}}</strong></article>
        <article><small>分析器版本</small><strong>{{model.profile.analyzer_version||'未记录'}}</strong></article>
        <article :class="flags.has_dynamic_shape?'flag-warning':'flag-ok'"><small>动态 Shape</small><strong>{{flags.has_dynamic_shape?'存在，评测时需使用受控输入':'未发现'}}</strong></article>
        <article :class="flags.has_control_flow?'flag-warning':'flag-ok'"><small>控制流算子</small><strong>{{flags.has_control_flow?'存在，需由平台编译验证':'未发现'}}</strong></article>
        <article :class="flags.uses_external_data?'flag-warning':'flag-ok'"><small>外部权重数据</small><strong>{{flags.uses_external_data?'存在，评测时需保证制品完整':'未发现'}}</strong></article>
      </div>
    </SectionCard>

    <SectionCard v-if="model.profile" title="算子统计与输入输出" description="算子分布用于理解模型计算结构；它不等同于某一平台的实际支持或性能结论。">
      <div class="operator-analysis-grid">
        <article class="operator-table-wrap"><h4>算子统计</h4><table class="data-table compact-table"><thead><tr><th>算子类型</th><th>数量</th><th>占比</th></tr></thead><tbody><tr v-for="[name,count] in operators" :key="String(name)"><td><strong>{{name}}</strong></td><td>{{count}}</td><td><div class="operator-ratio"><i :style="{width:`${totalOperators?Number(count)/totalOperators*100:0}%`}"/><span>{{totalOperators?(Number(count)/totalOperators*100).toFixed(1):0}}%</span></div></td></tr><tr v-if="!operators.length"><td colspan="3" class="muted">未记录算子统计。</td></tr></tbody></table></article>
        <article class="io-table-wrap"><h4>模型输入与输出</h4><table class="data-table compact-table"><thead><tr><th>类别</th><th>名称</th><th>Shape</th><th>数据类型</th></tr></thead><tbody><tr v-for="item in ioRows" :key="`${item.kind}-${item.name}`"><td><StatusBadge :tone="item.kind==='输入'?'progress':'neutral'">{{item.kind}}</StatusBadge></td><td><code>{{item.name||'未记录'}}</code></td><td><code>{{shape(item.shape)}}</code></td><td>{{item.element_type||'未记录'}}</td></tr><tr v-if="!ioRows.length"><td colspan="4" class="muted">未记录输入输出信息。</td></tr></tbody></table></article>
      </div>
    </SectionCard>

    <SectionCard title="评估可选平台" description="绿色平台当前具备可调度执行能力；暂不可用的平台会保留具体原因，恢复后可重新选择。">
      <div class="platform-summary"><article v-for="platform in platforms" :key="platform.id" class="platform-summary-card" :class="{unavailable:!platform.available}"><div><strong>{{platform.platform_type_name}} {{platform.version||''}}</strong><small>{{platform.available?'创建评估后将自动执行编译和板端性能阶段':platform.detail}}</small></div><StatusBadge :tone="platform.available?'success':'warning'">{{platform.available?'可评估':'暂不可用'}}</StatusBadge></article></div>
    </SectionCard>

    <SectionCard title="历史评估与报告" description="每一条 Flow 都是一次完整评测；完成后可查看评测报告或下载 PDF。">
      <EmptyState v-if="!flows.length" icon="◌" title="还没有历史评估" description="选择至少一个可用平台后，即可为这个模型创建首次评估。"><RouterLink v-if="canCreate" class="button-primary" :to="`/tasks/new?profile_id=${model.profile.id}`"><ActionIcon name="create" />创建评估</RouterLink></EmptyState>
      <div v-else class="table-wrap"><table class="data-table model-flow-table"><thead><tr><th>评测流程</th><th>目标平台</th><th>评测状态</th><th>当前进度</th><th class="table-actions">操作</th></tr></thead><tbody><tr v-for="flow in flows" :key="flow.id"><td><strong>{{flow.id}}</strong></td><td><span class="platform-list-tag">{{flow.platforms.join(' + ')}}</span></td><td><StatusBadge :tone="tone(flow.status)">{{state(flow.status)}}</StatusBadge></td><td><strong>{{flow.progress.label}}</strong><small>{{flow.progress.percent}}%</small></td><td class="table-actions"><div class="flow-row-actions"><RouterLink class="button-secondary" :to="`/flows/${flow.id}`"><ActionIcon name="view" />{{flow.progress.completed?'查看结果':'查看进度'}}</RouterLink><button v-if="flow.progress.completed" class="button-primary" @click="pdf(flow)"><ActionIcon name="download" />下载 PDF</button><button v-if="flow.progress.completed" class="row-danger-action" @click="deletingFlow=flow"><ActionIcon name="delete" />删除评估</button></div></td></tr></tbody></table></div>
    </SectionCard>
    <ConfirmDialog :open="Boolean(deletingFlow)" title="删除本次评估" description="将删除该次评测的内部阶段及其专属 Evidence、网页报告和 PDF；不会删除模型或其它评测。此操作无法恢复。" confirm-label="确认删除" @cancel="deletingFlow=undefined" @confirm="removeFlow" />
  </section>
  <section v-else class="page"><PageHeader title="模型详情" description="正在读取模型信息…"/><p v-if="error" class="feedback error">{{error}}</p></section>
</template>

<style scoped>
.asset-overview{display:grid;grid-template-columns:1.2fr 2fr 1.1fr 1fr;gap:14px;align-items:center}.asset-title{display:flex;gap:11px;align-items:center}.asset-title strong,.asset-title small{display:block}.asset-title small,.asset-fact small{margin-top:4px;color:#71839a}.asset-file-icon{display:grid;width:42px;height:42px;place-items:center;border-radius:11px;background:#e9f2ff;color:#1d70dc}.asset-file-icon :deep(.action-icon){width:23px;height:23px;margin:0}.asset-fact{display:grid;gap:5px}.asset-fact code{font-size:12px}.detail-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:17px}.flow-row-actions{display:flex;align-items:center;justify-content:flex-start;gap:9px;flex-wrap:wrap;margin:0;min-height:34px}.detail-actions :deep(.action-icon),.flow-row-actions :deep(.action-icon){width:15px;height:15px;margin-right:0;vertical-align:middle}.model-flow-table .table-actions{vertical-align:middle}.analysis-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.analysis-metrics>div{position:relative;display:grid;gap:4px;padding:13px 14px 13px 47px;border:1px solid #e0eaf5;border-radius:10px;background:#fbfdff}.analysis-metrics span{position:absolute;top:15px;left:15px;color:#2172df;font-size:20px}.analysis-metrics small,.analysis-detail-grid small{color:#71839a}.analysis-metrics strong{color:#173d68;font-size:1.18rem}.analysis-detail-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:13px}.analysis-detail-grid article{display:grid;gap:5px;padding:10px 12px;border-radius:8px;background:#f5f8fc}.analysis-detail-grid strong{font-size:13px;color:#294b70}.analysis-detail-grid .flag-ok{background:#edfbf2}.analysis-detail-grid .flag-warning{background:#fff6e6}.operator-analysis-grid{display:grid;grid-template-columns:1fr 1.15fr;gap:16px}.operator-table-wrap,.io-table-wrap{overflow:hidden;border:1px solid #e1eaf4;border-radius:10px;background:#fff}.operator-table-wrap h4,.io-table-wrap h4{margin:0;padding:11px 13px;border-bottom:1px solid #e5edf6;color:#1c4779}.compact-table{min-width:0}.compact-table th,.compact-table td{padding:.62rem .75rem}.operator-ratio{display:grid;grid-template-columns:minmax(40px,1fr) 45px;gap:7px;align-items:center}.operator-ratio i{height:6px;border-radius:9px;background:#2378e5}.operator-ratio span{font-size:12px;color:#59708c}.platform-list-tag{display:inline-block;padding:4px 8px;border-radius:999px;background:#edf5ff;color:#2160b1;font-size:12px;font-weight:700}.model-flow-table td small{display:block;margin-top:4px;color:#71839a}@media(max-width:900px){.asset-overview{grid-template-columns:1fr 1fr}.analysis-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.analysis-detail-grid{grid-template-columns:1fr 1fr}.operator-analysis-grid{grid-template-columns:1fr}}@media(max-width:620px){.asset-overview,.analysis-metrics,.analysis-detail-grid{grid-template-columns:1fr}.flow-row-actions{align-items:stretch}.flow-row-actions>*{flex:1;text-align:center}}
</style>
