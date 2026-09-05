<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import MetricCard from '../components/MetricCard.vue'
import SectionCard from '../components/SectionCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import ActionIcon from '../components/ActionIcon.vue'

const route=useRoute(), router=useRouter()
const flow=ref<any>(), report=ref<any>(), revisions=ref<any[]>([]), evidence=ref<any[]>([]), error=ref(''), deleteOpen=ref(false), revisionDeleting=ref<any>()
let timer:number|undefined
const text=(v:string)=>({QUEUED:'等待执行',CLAIMED:'已分配执行器',RUNNING:'执行中',SUCCEEDED:'成功',PARTIALLY_SUCCEEDED:'部分成功',FAILED:'失败',CANCELLED:'已取消',TIMEOUT:'超时',NOT_EXECUTED:'未执行',X5_COMPILE:'X5 编译',S100_COMPILE:'S100 编译',REAL_BOARD_SMOKE:'X5 板端性能',S100_BOARD_PERF:'S100 板端性能'} as Record<string,string>)[v]||v
const tone=(v:string)=>v==='SUCCEEDED'?'success':v==='PARTIALLY_SUCCEEDED'||v==='RUNNING'?'progress':v==='QUEUED'||v==='CLAIMED'?'warning':'danger'
const terminal=computed(()=>['SUCCEEDED','PARTIALLY_SUCCEEDED','FAILED','CANCELLED','TIMEOUT'].includes(flow.value?.status))
const platformSummary=computed(()=>report.value?.sections?.platforms||[])
const onnx=computed(()=>report.value?.sections?.onnx_model_profile||{})
const risks=computed(()=>report.value?.sections?.onnx_risks||[])
const onnxExtensions=computed(()=>report.value?.sections?.onnx_extensions||[])
const boundaries=computed(()=>report.value?.sections?.boundaries||{})
const reportStatus=(value:string)=>text(value||'NOT_EXECUTED')
const latency=(item:any)=>item.status==='SUCCEEDED'&&item.metrics?.average_latency_ms!==undefined?`${item.metrics.average_latency_ms} ms`:'未通过'
const compileTone=(item:any)=>tone(item.compile_status||'NOT_EXECUTED')
const structureRows=computed(()=>{
  const flags=onnx.value.structure_flags||{}
  return [
    ['节点数量',onnx.value.node_count??'未记录','▦'],['算子类别',onnx.value.operator_type_count??'未记录','⌘'],
    ['动态 Shape',flags.has_dynamic_shape?'存在':'未发现',flags.has_dynamic_shape?'!':'✓'],
    ['控制流',flags.has_control_flow?'存在':'未发现',flags.has_control_flow?'!':'✓'],
    ['外部权重',flags.uses_external_data?'存在':'未发现',flags.uses_external_data?'!':'✓'],
  ]
})
const safeSnapshots=computed(()=>Object.fromEntries(Object.entries(flow.value?.platform_snapshots||{}).map(([platform,snapshot]:[string,any])=>[platform,{平台:snapshot.platform_id||platform,目录版本:snapshot.catalog_version||'未记录',制品格式:snapshot.artifact_format||'未记录',固定Runner:snapshot.runner_release||'未记录',解析器:snapshot.parser||snapshot.parser_version||'未记录',规则版本:snapshot.rules_version||'已冻结'}])))
const platformNames=computed(()=>{const names:string[]=[];for(const [catalogId,snapshot] of Object.entries(flow.value?.platform_snapshots||{}) as [string,any][]) {const platform=snapshot.platform_id||snapshot.platform_type_name||catalogId;if(!names.includes(platform))names.push(platform)}for(const stage of flow.value?.stages||[])if(stage.platform&&!names.includes(stage.platform))names.push(stage.platform);for(const item of evidence.value||[])if(item.platform&&!names.includes(item.platform))names.push(item.platform);return names})
const stageGroups=computed(()=>platformNames.value.map(platform=>({platform,stages:(flow.value?.stages||[]).filter((stage:any)=>stage.platform===platform)})))
const evidenceGroups=computed(()=>platformNames.value.map(platform=>({platform,items:(evidence.value||[]).filter((item:any)=>(item.platform||'平台')===platform)})).filter(group=>group.items.length))
const toolchainNativeTypes=new Set(['BOARD_LOG','x5_compile_log','x5_compiled_model','s100_compile_log','s100_compiled_model','s100_board_profile_log','s100_board_profile_csv'])
const evidenceOrigin=(item:any)=>toolchainNativeTypes.has(item.type)?'工具链原生输出':'平台评测脚本输出'
const evidenceOriginTone=(item:any)=>toolchainNativeTypes.has(item.type)?'native':'script'
const displayTime=(value?:string)=>value ? value.slice(0, 19) : '未记录'
function save(value:Blob,name:string){const u=URL.createObjectURL(value),a=document.createElement('a');a.href=u;a.download=name;a.click();window.setTimeout(()=>URL.revokeObjectURL(u),1000)}
async function load(){try{flow.value=await api(`/evaluation-flows/${route.params.flowId}`);evidence.value=await api(`/evaluation-flows/${route.params.flowId}/evidence`);if(terminal.value){report.value=await api(`/evaluation-flows/${route.params.flowId}/report`);revisions.value=await api(`/evaluation-flows/${route.params.flowId}/report/revisions`)}else timer=window.setTimeout(load,5000)}catch(cause){error.value=cause instanceof Error?cause.message:'评估流程详情暂不可用。'}}
async function pdf(version?:number){try{const suffix=version?`?version=${version}`:'';save(await api(`/evaluation-flows/${route.params.flowId}/report/download${suffix}`) as Blob,`${route.params.flowId}-报告${version?`-V${version}`:''}.pdf`)}catch(cause){error.value=cause instanceof Error?cause.message:'PDF 下载失败。'}}
async function download(item:any){try{save(await api(`/evaluation-flows/${route.params.flowId}/evidence/${item.id}/download`) as Blob,`${item.platform||'platform'}-${item.type}`)}catch(cause){error.value=cause instanceof Error?cause.message:'Evidence 下载失败。'}}
function viewReport(){document.getElementById('report-preview')?.scrollIntoView({behavior:'smooth',block:'start'})}
async function remove(){try{await api(`/evaluation-flows/${route.params.flowId}`,{method:'DELETE'});await router.push('/')}catch(cause){error.value=cause instanceof Error?cause.message:'删除评估失败。'}finally{deleteOpen.value=false}}
async function removeRevision(){if(!revisionDeleting.value)return;try{await api(`/evaluation-flows/${route.params.flowId}/report/revisions/${revisionDeleting.value.version}`,{method:'DELETE'});revisionDeleting.value=undefined;await load()}catch(cause){error.value=cause instanceof Error?cause.message:'删除报告版本失败。'}}
onMounted(load); onUnmounted(()=>{if(timer)window.clearTimeout(timer)})
</script>

<template>
  <section v-if="flow" class="page flow-detail-page">
    <PageHeader title="评估流程详情" :description="`Flow ${flow.id}：一次用户评估，由各平台的编译与板端性能阶段独立执行并汇总。`" eyebrow="真实评估">
      <template #actions>
        <StatusBadge :tone="tone(flow.status)">{{ text(flow.status) }}</StatusBadge>
        <button :disabled="!terminal" @click="viewReport"><ActionIcon name="report" />查看评估报告</button>
        <button class="button-primary" :disabled="!terminal" @click="pdf(report?.revision?.version)"><ActionIcon name="download" />下载 PDF</button>
      </template>
    </PageHeader>
    <p v-if="error" class="feedback error">{{ error }}</p>
    <div class="metric-grid">
      <MetricCard icon="◌" label="对比平台" :value="Object.keys(flow.platform_snapshots||{}).length" :description="flow.stages.map((x:any)=>x.platform).filter((x:string,i:number,a:string[])=>a.indexOf(x)===i).join(' + ')"/>
      <MetricCard icon="◐" label="总体状态" :value="text(flow.status)" description="按各平台最终可达阶段汇总" :tone="tone(flow.status)"/>
      <MetricCard icon="▦" label="评测执行阶段" :value="flow.stages.length" description="编译与板端性能阶段的总数"/>
      <MetricCard icon="▤" label="评测依据" :value="evidence.length" description="基于当前 Flow 已归档的评测依据"/>
    </div>
    <SectionCard title="结论与下一步" description="只基于本次 Flow 的真实阶段与 Evidence，不混入 Candidate、管理员验证、其他 Flow 或 DEMO。">
      <p v-if="flow.status==='SUCCEEDED'">所有已选平台的最终阶段均成功。请在报告中按固定条件阅读性能事实，不作跨平台无条件排名。</p>
      <p v-else-if="flow.status==='PARTIALLY_SUCCEEDED'">部分平台已成功，其他平台的失败、取消或超时原因已保留；成功平台结果不会被覆盖。</p>
      <p v-else-if="terminal">本次 Flow 已结束，请查看阶段原因与 Evidence，再决定是否基于模型重新创建评估。</p>
      <p v-else>评估正在等待或执行中；页面每 5 秒局部刷新状态。</p>
    </SectionCard>
    <SectionCard title="平台阶段时间线" description="固定顺序：X5 编译后自动进入 X5 板端性能；S100 编译后自动进入 S100 板端性能。">
      <div class="platform-stage-groups"><article v-for="group in stageGroups" :key="group.platform" class="platform-stage-group"><header><strong>{{group.platform}}</strong><small>{{group.stages.length}} 个执行阶段</small></header><div class="timeline"><article v-for="stage in group.stages" :key="stage.id" class="timeline-item"><StatusBadge :tone="tone(stage.status)">{{text(stage.status)}}</StatusBadge><div><strong>{{text(stage.kind)}}</strong><small>执行阶段 {{stage.id}}</small><p v-if="stage.error_code" class="error">原因：{{stage.error_code}}</p></div></article></div></article></div>
    </SectionCard>
    <SectionCard v-if="report" id="report-preview" title="评测报告预览" :description="`报告版本 V${report.revision?.version} · ${report.notice}`">
      <div class="report-chapters">
        <article><h3>1. 多平台评估结论摘要</h3><p>{{report.sections.executive_summary?.conclusion}}</p><div class="platform-conclusion-grid"><article v-for="item in platformSummary" :key="item.platform" class="platform-conclusion-card"><header><strong>{{item.platform}}</strong><StatusBadge :tone="tone(item.status)">{{text(item.status)}}</StatusBadge></header><dl><div><dt>工具链版本</dt><dd>{{item.toolchain_version||'未记录'}}</dd></div><div><dt>模型编译</dt><dd><StatusBadge :tone="compileTone(item)">{{reportStatus(item.compile_status)}}</StatusBadge></dd></div><div><dt>推理时延</dt><dd :class="{'danger-text':item.status!=='SUCCEEDED'}">{{latency(item)}}</dd></div></dl></article></div><p class="muted">{{report.sections.executive_summary?.comparability}}</p></article>
        <article><h3>2. ONNX 模型检测概要</h3><p v-if="report.model?.unavailable">该历史 Flow 未冻结可验证的 ONNX Profile 快照；本版本不重新分析或猜测历史模型事实。</p><template v-else><div class="onnx-overview"><div><small>模型名称</small><strong>{{report.model?.filename||'未记录'}}</strong></div><div><small>文件大小</small><strong>{{report.model?.size_bytes??'未记录'}} 字节</strong></div><div><small>ONNX IR / Opset</small><strong>IR {{onnx.ir_version??'未记录'}} / {{(onnx.opset_imports||[]).map((item:any)=>item.version).join(', ')||'未记录'}}</strong></div><div><small>分析器</small><strong>{{report.model?.analyzer_version||'未记录'}}</strong></div></div><div class="analysis-table"><div v-for="row in structureRows" :key="row[0]" :class="['analysis-cell',row[2]==='!'?'analysis-warning':'analysis-ok']"><span>{{row[2]}}</span><small>{{row[0]}}</small><strong>{{row[1]}}</strong></div></div><div class="operator-summary"><strong>算子分布</strong><span v-for="(count,name) in onnx.operator_counts||{}" :key="name" class="operator-tag">{{name}} <b>{{count}}</b></span></div><div v-if="onnxExtensions.length" class="extension-summary"><strong>扩展检测结果</strong><span v-for="item in onnxExtensions" :key="item.module" class="extension-tag">✓ {{item.module}}：{{Object.entries(item.result||{}).map(([key,value])=>`${key}=${value}`).join('；')||'已完成'}}</span></div><ul class="risk-list"><li v-for="risk in risks" :key="risk.label"><span :class="risk.label.includes('未发现')?'risk-ok':'risk-warning'">{{risk.label.includes('未发现')?'✓':'!'}}</span><strong>{{risk.label}}</strong>：{{risk.meaning}}</li></ul></template></article>
        <article><h3>3. 各平台适配与板端测试结果</h3><div class="platform-result-grid"><article v-for="item in platformSummary" :key="item.platform" class="platform-result-card"><header><strong>{{item.platform}}</strong><StatusBadge :tone="tone(item.status)">{{text(item.status)}}</StatusBadge></header><dl class="platform-facts"><div><dt>最终阶段</dt><dd>{{text(item.stage_kind)}}</dd></div><div><dt>模型格式</dt><dd>{{item.artifact_format||'未记录'}}</dd></div><div><dt>测试执行器</dt><dd>{{item.runner_release||'未记录'}}</dd></div><div><dt>结果解析器</dt><dd>{{item.parser||'未记录'}}</dd></div><div class="platform-measurement"><dt>实测结果</dt><dd v-if="item.metrics?.fps!==undefined">FPS {{item.metrics.fps}}；平均延迟 {{item.metrics.average_latency_ms}} ms</dd><dd v-else class="danger-text">{{item.reason_code?'未通过：'+item.reason_code:'本阶段未采集可展示性能值。'}}</dd></div></dl></article></div></article>
        <article><h3>4. 后续优化建议</h3><p>{{report.sections.executive_summary?.next_step}}</p><p class="muted">输出一致性：{{boundaries.output_consistency||'未执行'}}；精度：{{boundaries.task_accuracy||'未验证'}}；稳定性：{{boundaries.stability||'未验证'}}；功耗：{{boundaries.power||'未验证'}}；部署推荐：{{boundaries.deployment_recommendation||'未验证'}}。</p></article>
      </div>
      <div v-if="revisions.length" class="report-revisions"><strong>报告版本</strong><span v-for="revision in revisions" :key="revision.id">V{{revision.version}} · {{revision.created_at}} <button @click="pdf(revision.version)"><ActionIcon name="download" />下载</button><button class="revision-delete" @click="revisionDeleting=revision"><ActionIcon name="delete" />删除</button></span></div>
    </SectionCard>
    <SectionCard title="评测过程依据与制品" description="按平台归类展示当前 Flow 已归档的评测依据与制品；每行左侧蓝色竖条代表工具链原生输出，绿色竖条代表平台评测脚本输出。下载时由后端再次校验归属。"><EmptyState v-if="!evidence.length" icon="▤" title="暂无评测依据" description="阶段执行后归档的日志、制品或性能依据会显示在这里。"/><div v-else class="platform-evidence-groups"><article v-for="group in evidenceGroups" :key="group.platform" class="platform-evidence-group"><header><strong>{{group.platform}}</strong><StatusBadge tone="neutral">{{group.items.length}} 项依据</StatusBadge></header><div class="table-wrap"><table class="data-table compact-evidence-table"><thead><tr><th>类型 / 阶段</th><th>SHA256</th><th>大小</th><th>时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in group.items" :key="item.id" :class="['evidence-row',evidenceOriginTone(item)]" :title="`产生方式：${evidenceOrigin(item)}`"><td><strong>{{item.type}}</strong><small>{{item.phase}}</small></td><td><code>{{item.sha256?.slice(0,16)||'未记录'}}…</code></td><td>{{item.size_bytes??'未记录'}}</td><td class="evidence-time">{{displayTime(item.created_at)}}</td><td><button v-if="item.can_download" @click="download(item)"><ActionIcon name="download" />下载</button></td></tr></tbody></table></div></article></div></SectionCard>
    <SectionCard title="冻结快照" description="版本、规则与解析器按创建 Flow 时冻结；技术事实不由用户编辑。"><details><summary>查看平台快照事实</summary><pre>{{JSON.stringify(safeSnapshots,null,2)}}</pre></details></SectionCard>
    <SectionCard v-if="terminal" title="删除本次评估" description="仅全部内部阶段终态时允许删除整次 Flow；删除本 Flow 时会同步清理它专属的报告版本和 PDF，不会删除模型、平台目录或其他评估。"><button class="button-danger" @click="deleteOpen=true"><ActionIcon name="delete" />删除本次评估</button></SectionCard>
    <ConfirmDialog :open="deleteOpen" title="删除本次评估" description="将删除本 Flow 已结束内部阶段及其仅被本流程引用的证据、报告版本与 PDF；此操作无法恢复。" confirm-label="确认删除" @cancel="deleteOpen=false" @confirm="remove"/>
    <ConfirmDialog :open="Boolean(revisionDeleting)" title="删除报告版本" :description="`将永久删除报告 V${revisionDeleting?.version || ''} 及其专属 PDF 制品；不会删除本次评估的阶段、评测依据、模型或其他报告版本。操作将记录审计日志，且无法恢复。`" confirm-label="确认删除版本" @cancel="revisionDeleting=undefined" @confirm="removeRevision"/>
  </section>
  <section v-else class="page"><PageHeader title="评估流程详情" description="正在读取 Flow…"/><p v-if="error" class="feedback error">{{error}}</p></section>
</template>

<style scoped>
.report-chapters{display:grid;gap:12px}.report-chapters>article{padding:16px 18px;border:1px solid #e2ebf5;border-radius:12px;background:#fbfdff}.report-chapters h3{margin:0 0 10px;color:#173d68;font-size:16px}.report-chapters p{margin:7px 0;line-height:1.6}.muted{color:#70849d}.danger-text{color:#c6322b;font-weight:700}.platform-conclusion-grid,.platform-result-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:12px}.platform-conclusion-card,.platform-result-card{padding:13px;border:1px solid #dce7f3;border-radius:10px;background:#fff}.platform-conclusion-card header,.platform-result-card header{display:flex;justify-content:space-between;align-items:center;padding-bottom:10px;border-bottom:1px solid #ebf0f6}.platform-conclusion-card dl,.platform-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:12px 0 0}.platform-facts{grid-template-columns:repeat(2,minmax(0,1fr))}.platform-conclusion-card dl div,.platform-facts div{padding:8px;border-radius:7px;background:#f5f8fc}.platform-facts .platform-measurement{grid-column:1/-1;background:#eef8f2}.platform-conclusion-card dt,.platform-facts dt{font-size:12px;color:#70849d}.platform-conclusion-card dd,.platform-facts dd{margin:4px 0 0;font-size:13px;font-weight:700;overflow-wrap:anywhere}.onnx-overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}.onnx-overview>div{padding:10px 12px;border:1px solid #e0e9f3;border-radius:8px;background:#fff}.onnx-overview small,.analysis-cell small{display:block;color:#71839a;font-size:12px}.onnx-overview strong{display:block;margin-top:4px;color:#173d68;overflow-wrap:anywhere}.analysis-table{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.analysis-cell{position:relative;padding:10px 11px 10px 32px;border-radius:8px}.analysis-cell>span{position:absolute;left:11px;top:12px;font-weight:800}.analysis-ok{background:#ecfbf1;color:#157342}.analysis-warning{background:#fff6e4;color:#a46105}.analysis-cell strong{display:block;margin-top:3px}.operator-summary,.extension-summary{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}.operator-summary>strong,.extension-summary>strong{color:#28496e}.operator-tag,.extension-tag{padding:4px 8px;border-radius:999px;background:#eaf3ff;color:#2061ba;font-size:12px}.operator-tag b{margin-left:3px}.extension-tag{background:#eef9f1;color:#237640}.risk-list{display:grid;gap:7px;margin:13px 0 0;padding:0;list-style:none}.risk-list li{padding:8px 10px;border-radius:7px;background:#f5f8fc}.risk-list span{display:inline-grid;width:18px;height:18px;place-items:center;margin-right:6px;border-radius:50%;font-weight:800}.risk-ok{color:#138747;background:#daf6e4}.risk-warning{color:#b26b07;background:#ffefcf}.report-revisions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid #e3edf7}.report-revisions span{padding:5px 8px;border-radius:6px;background:#f1f6fd;font-size:12px}.report-revisions button{margin-left:6px;padding:2px 6px;font-size:12px}.report-revisions .revision-delete{color:#a55b54;border-color:#edd5d1;background:#fff}.report-revisions .revision-delete:hover{color:#a3231e;border-color:#d99b94;background:#fff4f2}.action-icon{width:15px;height:15px;margin-right:5px;vertical-align:-2px}.platform-stage-groups,.platform-evidence-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}.platform-stage-group,.platform-evidence-group{overflow:hidden;border:1px solid #dce7f3;border-radius:11px;background:#fbfdff}.platform-stage-group>header,.platform-evidence-group>header{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border-bottom:1px solid #e1eaf4;background:#f5f9fe}.platform-stage-group>header strong,.platform-evidence-group>header strong{color:#173d68;font-size:1.05rem}.platform-stage-group>header small{color:#71839a}.platform-stage-group .timeline{padding:0 14px}.platform-stage-group .timeline-item{grid-template-columns:128px 1fr;padding:13px 0}.platform-evidence-group .table-wrap{padding:0}.compact-evidence-table{min-width:590px}.compact-evidence-table th,.compact-evidence-table td{padding:.7rem .6rem}.compact-evidence-table small{display:block;margin-top:3px;color:#71839a}@media(max-width:760px){.platform-stage-groups,.platform-evidence-groups{grid-template-columns:1fr}.platform-stage-group .timeline-item{grid-template-columns:1fr;gap:8px}.compact-evidence-table{min-width:550px}.onnx-overview,.analysis-table{grid-template-columns:repeat(2,minmax(0,1fr))}.platform-conclusion-card dl{grid-template-columns:1fr}}
.compact-evidence-table{min-width:610px}.evidence-row>td:first-child{position:relative;padding-left:16px}.evidence-row>td:first-child::before{position:absolute;content:"";left:4px;top:10px;bottom:10px;width:4px;border-radius:999px;background:#2e77d8}.evidence-row.script>td:first-child::before{background:#24a65a}.evidence-time{white-space:nowrap;font-variant-numeric:tabular-nums}@media(max-width:760px){.compact-evidence-table{min-width:580px}}
</style>
