<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute(); const router = useRouter()
const report = ref<any>()
const error = ref('')
const downloadError = ref('')
const task = ref<any>(); const recipient = ref(''); const includeModel = ref(false); const shareMessage = ref(''); const shares = ref<any[]>([])
let refreshTimer: number | undefined
const terminal = () => ['SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMEOUT'].includes(task.value?.status)
const taskStatusLabel = () => ({QUEUED:'等待 X5 Worker 执行', CLAIMED:'已分配给 X5 Worker', RUNNING:'正在执行', SUCCEEDED:'已完成', FAILED:'执行失败', CANCELLED:'已取消', TIMEOUT:'执行超时'} as Record<string,string>)[task.value?.status] || task.value?.status
const statusLabel = (value:unknown) => ({SUCCEEDED:'成功',FAILED:'失败',QUEUED:'等待执行',CLAIMED:'已分配执行器',RUNNING:'执行中',CANCELLED:'已取消',TIMEOUT:'执行超时',READY:'就绪',MEASURED:'已测量',BOARD_MEASURED:'板端实测',ACCESSIBLE:'可访问',NOT_EXECUTED:'未执行',NOT_VERIFIED:'未验证',NOT_COLLECTED:'未采集',NOT_COLLECTED_RUNTIME_INTERNAL_INPUT:'未采集（Runtime 内部输入）',NOT_COLLECTED_RUNTIME_PROFILE_ONLY:'未采集（仅有 Runtime profile）',NOT_DETECTED_IN_COMPILE_ALLOCATION:'编译分配中未检测到',NOT_SEPARABLE_BY_RUNTIME_COMMAND:'无法由 Runtime 命令单独区分'} as Record<string,string>)[String(value)] || String(value ?? '未记录')
const boardStageInProgress = () => ['QUEUED', 'CLAIMED', 'RUNNING'].includes(report.value?.sections?.x5_compile?.board_stage?.status)
async function loadShares() { if (task.value?.can_share) shares.value = await api(`/evaluation-tasks/${route.params.taskId}/shares`) as any[] }
async function load() {
  try {
    const taskData:any = await api(`/evaluation-tasks/${route.params.taskId}`); task.value = taskData
    if (terminal()) { report.value = await api(`/reports/${route.params.taskId}`); await loadShares(); if (boardStageInProgress()) refreshTimer = window.setTimeout(load, 5000) }
    else { report.value = undefined; refreshTimer = window.setTimeout(load, 5000) }
  } catch { error.value = '任务详情暂不可用，请稍后重试。' }
}
onMounted(load)
onUnmounted(() => { if (refreshTimer !== undefined) window.clearTimeout(refreshTimer) })

async function downloadPdf() {
  downloadError.value = ''
  try {
    const pdf = await api(`/reports/${route.params.taskId}/download`) as Blob
    const url = URL.createObjectURL(pdf)
    const link = document.createElement('a')
    link.href = url
    link.download = `${route.params.taskId}-report.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    // Some browsers start the download after the current event loop turn. Keep
    // the Blob URL alive briefly so a valid PDF is written before cleanup.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    downloadError.value = cause instanceof Error ? cause.message : 'PDF 下载失败，请稍后重试。'
  }
}

async function shareTask() {
  try { const result:any = await api(`/evaluation-tasks/${route.params.taskId}/shares`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({recipient:recipient.value,include_model:includeModel.value})}); shareMessage.value=`已共享此评估报告给 ${result.recipient}${result.include_model?'，并附带模型文件':'（未附带模型文件）'}`; recipient.value=''; includeModel.value=false; await loadShares() }
  catch (cause) { shareMessage.value=cause instanceof Error?cause.message:'共享失败。' }
}
async function revokeTask(subject:string) { try { await api(`/evaluation-tasks/${route.params.taskId}/shares/${encodeURIComponent(subject)}`, {method:'DELETE'}); shareMessage.value='已撤销共享。'; await loadShares() } catch (cause) { shareMessage.value=cause instanceof Error?cause.message:'撤销失败。' } }
async function deleteTask() {
  if (!confirm('确定永久删除此评估报告吗？相关分享关系与仅被该报告引用的证据将一并清理，无法恢复。')) return
  try { await api(`/evaluation-tasks/${route.params.taskId}`, {method:'DELETE'}); await router.push('/models') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '删除评估报告失败。' }
}
</script>

<template>
  <section v-if="task">
    <article v-if="!terminal()" class="card">
      <h2>X5 REAL 任务正在执行</h2>
      <p>任务号：<strong>{{ task.id }}</strong></p>
      <p>当前状态：<strong>{{ taskStatusLabel() }}</strong>。本页每 5 秒自动刷新一次，不会把排队任务误显示为已完成。</p>
      <p>完成编译后可在此查看编译记录，并继续发起板端性能评测。</p>
    </article>
    <template v-if="report">
    <h2>{{ report.mode === 'REAL' ? (report.task_kind === 'REAL_BOARD_SMOKE' ? 'X5 REAL 板端性能评测与报告' : 'X5 REAL 编译任务与报告') : 'DEMO 任务详情与报告预览' }}</h2>
    <p class="notice">{{ report.mode === 'REAL' ? report.notice : report.mock_notice }}</p>
    <template v-if="report.mode === 'REAL' && report.task_kind === 'REAL_BOARD_SMOKE'">
      <article class="card"><h3>板端预检、加载与受控 Runtime 调用</h3><p>预检：<strong>{{ statusLabel(report.sections.x5_board_smoke.board_preflight) }}</strong>；制品下发：{{ statusLabel(report.sections.x5_board_smoke.model_transfer) }}</p><p>加载：{{ statusLabel(report.sections.x5_board_smoke.model_load) }}；Runtime 调用：{{ statusLabel(report.sections.x5_board_smoke.single_runtime_invocation) }}</p></article>
      <h3>制品与输入/输出证据</h3><p>model.bin SHA256：{{ report.sections.x5_board_smoke.model_bin_sha256 }}</p><p>输入：{{ statusLabel(report.sections.x5_board_smoke.input_sha256) }}；输出：{{ statusLabel(report.sections.x5_board_smoke.output_sha256) }}</p>
      <template v-if="report.sections.x5_board_smoke.performance?.status === 'MEASURED'">
        <h3>固定 Runtime profile 性能记录</h3>
        <article class="card"><p>证据等级：{{ statusLabel(report.sections.x5_board_smoke.performance.evidence_level) }}；Runner：{{ report.sections.x5_board_smoke.performance.runner }}</p><p>系统：{{ report.sections.x5_board_smoke.performance.environment?.system }}；Runtime：{{ report.sections.x5_board_smoke.performance.environment?.runtime_version }}；BPU：{{ statusLabel(report.sections.x5_board_smoke.performance.environment?.bpu_access) }}</p><p>FPS：<strong>{{ report.sections.x5_board_smoke.performance.metrics.fps }}</strong>；平均延迟：<strong>{{ report.sections.x5_board_smoke.performance.metrics.average_latency_ms }} ms</strong></p><p>模型：{{ report.sections.x5_board_smoke.performance.running_condition.model_name }}；线程：{{ report.sections.x5_board_smoke.performance.running_condition.thread_num }}；帧数：{{ report.sections.x5_board_smoke.performance.running_condition.frame_count }}；运行时间：{{ report.sections.x5_board_smoke.performance.running_condition.run_time_ms }} ms</p></article>
        <h4>分段耗时</h4><table><thead><tr><th>分段</th><th>执行侧</th><th>平均 / 最小 / 最大（ms）</th></tr></thead><tbody><tr v-for="segment in report.sections.x5_board_smoke.performance.segments" :key="segment.name"><td>{{ segment.name }}</td><td>{{ segment.processor }}</td><td>{{ segment.average_ms }} / {{ segment.minimum_ms }} / {{ segment.maximum_ms }}</td></tr></tbody></table>
        <p>CPU 执行段：{{ report.sections.x5_board_smoke.performance.cpu_execution_segment_present ? '存在' : '未记录' }}；模型 CPU 算子：{{ statusLabel(report.sections.x5_board_smoke.performance.model_cpu_operator_assessment.status) }}。CPU 耗时不能单独证明模型存在 CPU 算子，结论以编译分配日志为准。</p>
        <h3>X5 性能优化下一步</h3><p>{{ report.sections.x5_board_smoke.performance.guidance?.scope }}</p><ul><li v-for="item in report.sections.x5_board_smoke.performance.guidance?.items" :key="item.code">{{ item.message }}</li></ul>
      </template>
      <h3>未验证边界</h3><p>上述仅是固定 Runtime profile 的本次板端测量；精度、稳定性、功耗和推荐部署均为未验证，不可据此作交付结论。</p>
      <h3>平台目录与执行快照</h3><p>平台：{{ report.sections.platform_governance?.platform_id }}；Catalog：{{ report.sections.platform_governance?.catalog_version }}；Binding：{{ report.sections.platform_governance?.binding_id }}；Worker：{{ report.sections.platform_governance?.worker_id }}</p>
    </template>
    <template v-else-if="report.mode === 'REAL'">
      <article class="card"><h3>编译状态</h3><strong>{{ statusLabel(report.sections.x5_compile.status) }}</strong><p>工具链：{{ report.sections.x5_compile.toolchain?.hb_mapper }}；Runner：{{ report.sections.x5_compile.runner_version }}</p></article>
      <h3>ONNX 模型检测概要</h3><p>节点数：{{ report.sections.onnx_model_profile.node_count }}；算子：{{ report.sections.onnx_model_profile.operator_counts }}</p>
      <h3>制品与证据</h3><table><thead><tr><th>名称</th><th>格式</th><th>SHA256</th></tr></thead><tbody><tr v-for="item in report.sections.x5_compile.artifacts" :key="item.sha256"><td>{{ item.filename || item.type }}</td><td>{{ item.format || '-' }}</td><td>{{ item.sha256 }}</td></tr></tbody></table>
      <h3>自动板端性能阶段</h3><p>状态：{{ statusLabel(report.sections.x5_compile.board_stage?.status) }}<template v-if="report.sections.x5_compile.board_stage?.task_id">；<RouterLink :to="`/tasks/${report.sections.x5_compile.board_stage.task_id}`">查看板端性能结果</RouterLink><span v-if="report.sections.x5_compile.board_stage?.reason">；{{report.sections.x5_compile.board_stage.reason}}</span></template><template v-else>；{{ report.sections.x5_compile.board_stage?.reason || '尚未创建板端阶段' }}</template></p><small v-if="boardStageInProgress()">板端性能阶段仍在后台执行，本页每 5 秒自动刷新状态。</small>
      <h3>未验证边界</h3><p>本编译记录不重复展示板端事实；请查看上方自动板端性能阶段。精度：{{ statusLabel(report.sections.x5_compile.accuracy) }}；稳定性：{{ statusLabel(report.sections.x5_compile.stability) }}；推荐部署：{{ statusLabel(report.sections.x5_compile.deployment_recommendation) }}</p>
      <h3>平台目录与执行快照</h3><p>平台：{{ report.sections.platform_governance?.platform_id }}；Catalog：{{ report.sections.platform_governance?.catalog_version }}；Binding：{{ report.sections.platform_governance?.binding_id }}；Worker：{{ report.sections.platform_governance?.worker_id }}</p>
    </template>
    <template v-else>
      <h3>多平台评估结论摘要</h3><p>{{ report.sections.multi_platform_summary }}</p><h3>ONNX 模型检测概要</h3><p>节点数：{{ report.sections.onnx_model_profile.node_count }}</p><h3>各平台适配结果</h3><table><thead><tr><th>平台</th><th>状态</th><th>来源</th></tr></thead><tbody><tr v-for="item in report.sections.platform_results" :key="item.platform"><td>{{ item.platform }}</td><td>{{ item.status }}</td><td>{{ item.source }}</td></tr></tbody></table>
    </template>
    <button type="button" class="link-button" @click="downloadPdf">下载 {{ report.mode === 'REAL' ? (report.task_kind === 'REAL_BOARD_SMOKE' ? 'X5 板端性能评测 PDF' : 'X5 编译记录 PDF') : 'Mock PDF' }}</button>
    <button v-if="task?.can_delete" type="button" @click="deleteTask">删除评估报告</button>
    <p v-if="downloadError" class="error">{{ downloadError }}</p>
    <form v-if="task?.can_share" class="card" @submit.prevent="shareTask"><h3>共享本次评估</h3><p>共享的是本次任务详情、报告和 PDF；接收者始终会在模型列表看到模型名称及本次报告。</p><label>接收人用户名或 SSO Subject <input v-model="recipient" required></label><label><input v-model="includeModel" type="checkbox"> 同时附带 ONNX 模型文件（允许接收者下载并基于该模型创建自己的评估）</label><button>共享本次评估</button><p v-if="shareMessage">{{shareMessage}}</p><h4>已共享给</h4><p v-if="!shares.length">尚未共享。</p><ul v-else><li v-for="share in shares" :key="share.recipient">{{ share.username || share.recipient }}{{share.include_model?'（含模型）':'（不含模型）'}} <button type="button" @click="revokeTask(share.recipient)">撤销</button></li></ul></form>
    <article v-if="report.mode === 'REAL' && report.task_kind === 'X5_COMPILE' && task.status === 'SUCCEEDED'" class="card"><h3>板端性能评测</h3><p>编译成功后，系统会自动将不可变 model.bin 加入已绑定 X5 板端的固定 <code>hrt_model_exec perf</code> 队列；无需手动创建第二个评测。精度、稳定性、功耗和部署推荐不在本预设范围内。</p></article>
    </template>
  </section>
  <p v-else-if="error" class="error">{{ error }}</p>
  <p v-else>正在加载任务与报告…</p>
</template>
