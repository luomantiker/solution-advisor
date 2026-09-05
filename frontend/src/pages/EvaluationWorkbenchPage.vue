<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import MetricCard from '../components/MetricCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import ActionIcon from '../components/ActionIcon.vue'

type FlowSummary = { id:string; status:string; preset:string; platforms:string[]; model_asset_id:string|null; model_name:string; created_at?:string }
const data = ref<any>(), error = ref(''), selectedId = ref('')
const terminal = new Set(['SUCCEEDED','PARTIALLY_SUCCEEDED','FAILED','CANCELLED','TIMEOUT'])
const statusText = (value:string) => ({QUEUED:'等待执行',CLAIMED:'已分配执行器',RUNNING:'执行中',SUCCEEDED:'成功',PARTIALLY_SUCCEEDED:'部分成功',FAILED:'失败',CANCELLED:'已取消',TIMEOUT:'超时'} as Record<string,string>)[value] || value
const tone = (value:string) => value==='SUCCEEDED'?'success':value==='PARTIALLY_SUCCEEDED'||value==='RUNNING'?'progress':value==='QUEUED'||value==='CLAIMED'?'warning':'danger'
const resultTitle = (value:string) => ({SUCCEEDED:'本次评估已成功完成',PARTIALLY_SUCCEEDED:'本次评估部分完成',FAILED:'本次评估未成功完成',CANCELLED:'本次评估已取消',TIMEOUT:'本次评估已超时'} as Record<string,string>)[value] || '系统正在受控执行'
const resultDescription = (value:string) => ({SUCCEEDED:'可查看按本次 Flow 冻结快照生成的阶段事实、Evidence、网页报告和 PDF。',PARTIALLY_SUCCEEDED:'部分平台已完成；其余平台的失败、取消或超时事实已保留在流程详情中。',FAILED:'请进入完整流程查看失败阶段与已保留的 Evidence，再决定后续处理。',CANCELLED:'该 Flow 已停止执行；已产生的受控阶段事实可在流程详情中查看。',TIMEOUT:'该 Flow 已结束；请在流程详情中查看超时阶段与已保留的 Evidence。'} as Record<string,string>)[value] || '编译和板端性能阶段作为内部阶段独立执行；页面会在 Flow 详情中局部刷新真实进度。'
const statusIcon = (value:string) => ({SUCCEEDED:'✓',PARTIALLY_SUCCEEDED:'◐',FAILED:'!',CANCELLED:'×',TIMEOUT:'⌛',QUEUED:'○',CLAIMED:'◌',RUNNING:'◐'} as Record<string,string>)[value] || '•'
function timestamp(value:string|undefined){ return value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '时间未记录' }
const allFlows = computed<FlowSummary[]>(() => {
  if (!data.value) return []
  const unique = new Map<string, FlowSummary>()
  for (const item of [...data.value.continue_flows, ...data.value.recent_flows, ...data.value.recent_reports]) unique.set(item.id, item)
  return [...unique.values()]
})
const selected = computed(() => allFlows.value.find(item => item.id === selectedId.value))
function select(flow:FlowSummary){ selectedId.value = flow.id }
function domainItems(domain:'continuing'|'recent'|'reports'){
  if (!data.value) return []
  if (domain === 'continuing') return data.value.continue_flows as FlowSummary[]
  if (domain === 'reports') return data.value.recent_reports as FlowSummary[]
  return (data.value.recent_flows as FlowSummary[]).slice(0, 6)
}
async function load(){
  try {
    data.value = await api('/evaluation-workbench')
    selectedId.value = data.value.continue_flows[0]?.id || data.value.recent_flows[0]?.id || data.value.recent_reports[0]?.id || ''
  } catch(cause) { error.value = cause instanceof Error ? cause.message : '工作台加载失败，请稍后重试。' }
}
onMounted(load)
</script>

<template>
  <section class="page user-workbench-page">
    <PageHeader title="评估工作台" description="从模型选择到多平台真实评估、报告与 PDF，均以本次 Flow 冻结快照为准。" eyebrow="我的评估" />
    <p v-if="error" class="feedback error">{{error}}</p>
    <template v-else-if="data">
      <div class="metric-grid workbench-metrics">
        <MetricCard icon="◐" label="进行中评估" :value="data.metrics.in_progress" description="等待或正在执行的 Flow" tone="progress"/>
        <MetricCard icon="●" label="已完成评估" :value="data.metrics.completed" description="可在报告中心继续查看" tone="success"/>
        <MetricCard icon="▦" label="我的模型" :value="data.metrics.models" description="本人可创建评估的模型"/>
        <MetricCard icon="▤" label="可下载报告" :value="data.metrics.reports" description="已结束 Flow 的报告与 PDF"/>
      </div>
      <div class="workbench-split">
        <aside class="workbench-list-panel" aria-label="评估业务列表">
          <header><div><p class="panel-eyebrow">我的评估</p><h3>按业务状态查看</h3></div><button class="icon-button" title="刷新工作台" aria-label="刷新工作台" @click="load"><ActionIcon name="refresh"/></button></header>
          <section class="workbench-domain">
            <div class="domain-heading"><strong>执行中的评估</strong><span>{{domainItems('continuing').length}}</span></div>
            <p v-if="!domainItems('continuing').length" class="domain-empty">当前没有等待或执行中的评估。</p>
            <button v-for="flow in domainItems('continuing')" :key="flow.id" class="workbench-list-item" :class="{selected:flow.id===selectedId}" @click="select(flow)"><span class="list-item-main"><strong>{{flow.model_name}}</strong><small>{{flow.platforms.join(' + ')}} · {{timestamp(flow.created_at)}}</small></span><StatusBadge :tone="tone(flow.status)">{{statusText(flow.status)}}</StatusBadge></button>
          </section>
          <section class="workbench-domain">
            <div class="domain-heading"><strong>最近评估</strong><span>{{domainItems('recent').length}}</span></div>
            <p v-if="!domainItems('recent').length" class="domain-empty">上传 ONNX 模型后即可创建评估。</p>
            <button v-for="flow in domainItems('recent')" :key="flow.id" class="workbench-list-item" :class="{selected:flow.id===selectedId}" @click="select(flow)"><span class="list-item-main"><strong>{{flow.model_name}}</strong><small>{{flow.platforms.join(' + ') || '平台尚未登记'}} · {{timestamp(flow.created_at)}}</small></span><StatusBadge :tone="tone(flow.status)">{{statusText(flow.status)}}</StatusBadge></button>
          </section>
          <section class="workbench-domain report-domain"><div class="domain-heading"><strong>评估报告</strong><span>{{domainItems('reports').length}}</span></div><p class="domain-note">已结束 Flow 的网页报告与 PDF 统一从此处进入。</p><RouterLink class="text-link" to="/reports">查看全部评估报告 →</RouterLink></section>
        </aside>
        <section class="workbench-detail-panel" aria-live="polite">
          <EmptyState v-if="!selected" icon="◌" title="选择一项评估" description="从左侧列表选择正在执行或已完成的评估，在这里查看其状态、范围和后续操作。"><RouterLink class="button-primary" to="/models"><ActionIcon name="model"/>进入模型列表</RouterLink></EmptyState>
          <template v-else>
            <header class="detail-panel-header"><div><p class="panel-eyebrow">评估摘要</p><h3>{{selected.model_name}}</h3><code>Flow：{{selected.id}}</code></div><StatusBadge :tone="tone(selected.status)">{{statusText(selected.status)}}</StatusBadge></header>
            <div class="detail-facts"><div><span class="fact-icon">▦</span><div><span>目标平台</span><strong>{{selected.platforms.join(' + ') || '平台尚未登记'}}</strong></div></div><div><span class="fact-icon">◷</span><div><span>创建时间</span><strong>{{timestamp(selected.created_at)}}</strong></div></div><div><span class="fact-icon">⚙</span><div><span>受控预设</span><strong>{{selected.preset}}</strong></div></div><div><span class="fact-icon" :class="`tone-${tone(selected.status)}`">{{statusIcon(selected.status)}}</span><div><span>当前状态</span><strong :class="`status-text-${tone(selected.status)}`">{{statusText(selected.status)}}</strong></div></div></div>
            <section class="detail-result-summary" :class="`tone-${tone(selected.status)}`"><div class="result-icon">{{statusIcon(selected.status)}}</div><div><p class="panel-eyebrow">{{terminal.has(selected.status) ? '评估结果' : '执行进度'}}</p><strong>{{resultTitle(selected.status)}}</strong><p>{{resultDescription(selected.status)}}</p></div></section>
            <section class="detail-guidance"><div class="guidance-heading"><span>▤</span><div><p class="panel-eyebrow">评估范围与追溯</p><h4>一次评估，一条可追溯流程</h4></div></div><div class="platform-chip-row"><span v-for="platform in selected.platforms" :key="platform" class="platform-chip">{{platform}}</span><span v-if="!selected.platforms.length" class="platform-chip muted-chip">平台尚未登记</span></div><p>每个选中平台均按本次 Flow 冻结的受控预设组织编译与板端性能阶段；流程详情展示阶段状态和 Evidence，已结束评估可在报告中心查看网页报告或下载 PDF。</p></section>
            <div class="detail-actions"><RouterLink class="button-primary" :to="`/flows/${selected.id}`"><ActionIcon name="view"/>{{tone(selected.status)==='danger'?'查看失败原因与流程':'查看完整流程'}}</RouterLink><RouterLink v-if="terminal.has(selected.status)" class="row-secondary-action" to="/reports"><ActionIcon name="report"/>查看评估报告</RouterLink></div>
            <footer class="detail-footnote">仅展示当前用户可访问的 Flow 摘要；执行 Host、Worker、Binding、镜像与凭据不会在普通用户工作台显示。</footer>
          </template>
        </section>
      </div>
    </template>
    <div v-else class="workbench-loading"><span class="loading-dot"></span>正在读取本人评估、模型与报告摘要…</div>
  </section>
</template>
