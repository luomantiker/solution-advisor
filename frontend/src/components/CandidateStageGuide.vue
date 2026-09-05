<script setup lang="ts">
const props = defineProps<{
  stage: 'DISCOVERED' | 'INTEGRATING' | 'MANAGED'
  claimedBy?: string | null
  canEdit?: boolean
  validationState?: string | null
}>()

const content = {
  DISCOVERED: {
    title: '接入引导：发现镜像',
    context: '这是一条 HostAgent 只读发现记录。它尚未成为平台，也不会创建 Binding、Worker 或用户可选能力。',
    input: '填写平台类型、目标版本和接入档案说明。平台类型与版本会成为后续审核、发布和复用的可审查标识。',
    action: '生成 Candidate 后，系统会锁定本次镜像发现事实，并把它转入“接入进行中”。',
    evidence: '当前没有接入 Evidence；候选项创建后才能登记固定规则、执行离线检查和真实验证。',
  },
  INTEGRATING: {
    title: '接入引导：人工接入中',
    context: 'Candidate 由一位管理员人工认领。认领期间，其他管理员只读，避免重复调整同一份接入资料。',
    input: '步骤 1 登记显示名称、接入档案和固定编译/板端规则；步骤 2 检查离线契约；步骤 3 选择受控模型进行真实验证。',
    action: '保存规则会使旧验证结果失效；通过真实验证后才可提交审核目录。释放或超级管理员强制释放会先清理本次接入资料。',
    evidence: '可在工作区查看本 Candidate 当前修订产生的规则、离线检查和真实验证 Evidence；旧资料不会交给下一位管理员。',
  },
  MANAGED: {
    title: '接入引导：已发布平台',
    context: '该镜像对应的 Candidate 已审核发布为 Catalog。Catalog 是可追溯的平台发布物，不等同于当前一定可调度。',
    input: '后续评估不再填写接入参数；用户只能选择已经满足健康 Binding、在线 HostAgent 与 READY Worker 的平台。',
    action: '系统根据 Catalog、Binding、Worker、固定 Runner 和发现镜像校验决定是否可调度。',
    evidence: '发布时冻结的规则、Runner、验证 Evidence 和审计会保留；用户报告只读取其自身 Flow 的快照与 Evidence。',
  },
}[props.stage]

const flowSteps = [
  {
    number: '步骤 1',
    title: '发现镜像',
    detail: 'HostAgent 只读上报镜像事实；在“已发现镜像”中确认镜像来源与目标平台版本。',
    note: '此时只是待接入镜像，不会自动创建 Candidate、Binding、Worker 或用户可选平台。',
  },
  {
    number: '步骤 2',
    title: '创建并人工认领 Candidate',
    detail: '管理员创建 Candidate 后领取处理权；同一 Candidate 同时仅允许一位管理员编辑。',
    note: '认领人可主动释放；超级管理员强制释放前会清理本次接入资料，不会直接转交进行中的材料。',
  },
  {
    number: '步骤 3',
    title: '登记平台资料与固定规则',
    detail: '在接入工作区填写显示名称、接入档案、固定编译规则和固定板端验证规则。',
    note: '规则是可审查的平台资料，不接受用户任务直接输入 Shell、Docker 参数、路径或凭据。修改规则会使旧验证失效。',
  },
  {
    number: '步骤 4',
    title: '离线检查与真实验证',
    detail: '先完成离线契约检查，再选择受控模型发起真实编译与板端验证，并回传 Artifact 和 Evidence。',
    note: '离线检查通过不等于真实验证成功；缺少真实 Evidence 时不能进入审核发布。',
  },
  {
    number: '步骤 5',
    title: '审核发布与受控调度',
    detail: '审核通过后生成可追溯 Catalog；满足健康 Binding、在线 HostAgent、READY Worker 和 Runner 匹配时才可供用户选择。',
    note: '发布会冻结规则、Runner 与验证事实；用户报告只读取其自身 Flow 快照和 Evidence。',
  },
]
</script>

<template>
  <section class="candidate-stage-guide" :data-stage="stage">
    <template v-if="stage==='MANAGED'">
      <div class="flow-guide-heading">
        <div><h3>平台接入流程引导</h3><p>按以下步骤完成平台纳管；每一步均保留可审查资料与审计记录。</p></div>
      </div>
      <div class="flow-guide-steps">
        <template v-for="(item, index) in flowSteps" :key="item.number">
          <article class="flow-guide-step">
            <small>{{ item.number }}：{{ item.title }}</small>
            <p>{{ item.detail }}</p>
            <em>{{ item.note }}</em>
          </article>
          <span v-if="index < flowSteps.length - 1" class="flow-guide-arrow" aria-hidden="true">→</span>
        </template>
      </div>
    </template>
    <template v-else>
      <h3>{{ content.title }}</h3>
      <dl>
        <dt>当前上下文</dt><dd>{{ content.context }}</dd>
        <dt>需要填写/确认</dt><dd>{{ content.input }}</dd>
        <dt>系统将执行</dt><dd>{{ content.action }}</dd>
        <dt>资料与证据</dt><dd>{{ content.evidence }}</dd>
      </dl>
      <p v-if="stage==='INTEGRATING'" class="claim-note">
        <strong>认领状态：</strong>{{ claimedBy ? (canEdit ? '由我认领，可继续编辑。' : `由 ${claimedBy} 认领，当前为只读。`) : '尚未认领，领取后才可编辑。' }}
        <span v-if="validationState"> 当前真实验证：{{ validationState }}。</span>
      </p>
    </template>
  </section>
</template>

<style scoped>
.candidate-stage-guide{margin:14px 0;padding:13px 14px;border:1px solid #d9e6f5;border-left:4px solid #2875d9;border-radius:10px;background:#f8fbff;color:#38516d}.candidate-stage-guide[data-stage="INTEGRATING"]{border-left-color:#e69a23;background:#fffaf0}.candidate-stage-guide[data-stage="MANAGED"]{border-left-color:#2875d9;background:#f8fbff}.candidate-stage-guide h3{margin:0 0 9px;color:#173d68;font-size:15px}.candidate-stage-guide dl{margin:0;display:grid;gap:8px}.candidate-stage-guide dt{font-size:12px;font-weight:700;color:#1d5da6}.candidate-stage-guide dd{margin:0;font-size:13px;line-height:1.55}.claim-note{margin:10px 0 0;padding-top:9px;border-top:1px solid #dbe7f3;font-size:13px;line-height:1.5}
.flow-guide-heading h3{margin-bottom:.2rem}.flow-guide-heading p{margin:0;font-size:.78rem;line-height:1.45}.flow-guide-steps{display:flex;align-items:stretch;gap:.55rem;margin-top:.8rem;overflow-x:auto;padding-bottom:.15rem}.flow-guide-step{display:flex;flex:1 0 185px;flex-direction:column;border:1px solid #d5e4f5;border-radius:9px;background:#fff;padding:.7rem .75rem}.flow-guide-step small{color:#1f62ad;font-size:.78rem;font-weight:800}.flow-guide-step p{margin:.42rem 0;color:#294965;font-size:.76rem;line-height:1.45}.flow-guide-step em{margin-top:auto;border-top:1px solid #e3edf7;padding-top:.42rem;color:#657f98;font-size:.7rem;font-style:normal;line-height:1.4}.flow-guide-arrow{display:grid;place-items:center;align-self:center;color:#2875d9;font-size:1.35rem;font-weight:800}@media(max-width:900px){.flow-guide-steps{align-items:center}.flow-guide-arrow{transform:rotate(90deg)}}
</style>
