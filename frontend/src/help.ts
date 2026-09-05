export type HelpSection = { title: string, items: string[] }

export const HELP_VERSION = 'workbench-help-1.0'

function pageSection(path: string): HelpSection {
  if (path === '/') return { title: '当前页面：评估工作台', items: [
    '工作台只汇总您自己的真实评估流程、进度和已生成报告；不会显示 Worker、镜像、Host 或命令。',
    '请选择“新建评估”后，依次选择模型、平台和固定预设。内部编译与板端阶段会在详情页汇总展示。',
  ] }
  if (path === '/upload') return { title: '当前页面：上传模型', items: [
    '上传完成后，系统会生成通用 ONNX 检测结果；模型和后续评估默认仅归当前用户可见。',
    '请从模型详情创建评估。页面不接收 Worker、镜像、命令、板端地址或凭据。',
  ] }
  if (path.startsWith('/models')) return { title: '当前页面：模型与评估', items: [
    '从模型详情可创建一次评估流程、查看进度、网页报告和 PDF。',
    'Evidence 仅向该模型所有者及被明确授权的共享对象开放。',
  ] }
  if (path.startsWith('/flows')) return { title: '当前页面：评估流程详情', items: [
    '一次评估会在每个平台内部执行编译和板端性能阶段；不同平台的实际结果分别保留。',
    '性能事实受模型、输入、线程、帧数与 Runtime 条件限制，未验证项不会被推断为结论。',
  ] }
  if (path.startsWith('/reports')) return { title: '当前页面：我的报告', items: [
    '每份报告对应一次真实 EvaluationFlow，不会按内部编译或板端阶段拆分为多份用户报告。',
    '网页报告与 PDF 都只读取该 Flow 冻结快照及其 Evidence；未验证项不会被标记为通过。',
  ] }
  if (path.startsWith('/people')) return { title: '当前页面：人员管理', items: [
    '新建本地人员默认初始密码为 Realthon_1，账号创建后直接处于 ACTIVE 状态。',
    '重置密码、停用和角色调整会撤销应失效会话；用户可自行修改密码后重新登录。',
    '管理员仅可查看和管理普通用户；超级管理员可管理管理员与普通用户，并承担最高权限事项。',
    '配额与能力范围的数据字段已预留，当前尚未形成可执行限制，因此不在页面配置。',
  ] }
  if (path.startsWith('/admin')) return { title: '当前页面：平台治理', items: [
    'Candidate 未认领时，ACTIVE 管理员可领取；已认领后只有认领人可以编辑、测试、推进或手动释放。',
    '手动释放会清理本次接入资料。常见受阻原因包括固定 Runner 尚未安装、当前修订尚未验证或资料不完整。',
    'Candidate 的状态、可执行动作和资料清理结果以工作台当前条目及后端授权为准。',
  ] }
  return { title: '当前页面', items: ['请按页面中的操作说明完成受控流程；系统不会接受网页直接输入的执行环境参数。'] }
}

export function helpSections(role: string | undefined, path: string): HelpSection[] {
  const sections = [pageSection(path), { title: '新用户快速上手', items: [
    '先在“模型评估”上传 ONNX 文件，等待通用结构分析完成；分析成功仅表示模型结构已读取，不等于平台已验证。',
    '打开模型详情，查看模型属性、算子统计和可评估平台；点击“创建评估”依次确认模型、平台和受控预设。',
    '在“首页”或模型详情进入评估 Flow：每个平台都有独立编译和板端性能阶段，结果会分别汇总。',
    '评估结束后点击“查看评估报告”阅读网页报告，或下载 PDF；报告只使用本次 Flow 冻结的模型快照与评测依据。',
    '“通知消息”仅汇总当前账号可访问的业务动态，可按维度筛选、标记已读或清理显示；不会删除评估和审计事实。',
  ] }]
  if (role === 'SUPER_ADMIN') sections.push({ title: '超级管理员职责', items: [
    '可管理人员，并对强制释放和清理后指定 ACTIVE 管理员填写原因；审计记录会保留责任与影响。',
    '强制释放会先清理原认领人的接入资料；指定管理员从干净工作区开始，不继承进行中的材料。',
  ] })
  else if (role === 'ADMIN') sections.push({ title: '管理员协作边界', items: [
    '认领人可继续处理或主动释放；其他管理员保持只读，后端会拒绝编辑、测试和推进请求。',
    '可在人员管理中创建、启停和重置普通用户密码；对管理员与超级管理员的操作由后端返回 403。',
    '如遇修订冲突，请刷新工作台后基于最新状态重新操作，避免覆盖他人的变更。',
  ] })
  else sections.push({ title: '普通用户边界', items: [
    '可上传自己的模型、创建评估、查看获授权的 Evidence、网页报告和 PDF。',
    '不能进入人员管理或平台治理，也不能查看其他用户的模型、任务、报告或制品引用。',
  ] })
  return sections
}
