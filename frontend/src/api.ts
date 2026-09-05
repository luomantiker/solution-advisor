const base = import.meta.env.VITE_API_BASE ?? '/api/v1'
const tokenKey = 'solution-advisor-access-token'
export const accessToken = () => sessionStorage.getItem(tokenKey) || ''
export const saveAccessToken = (value: string) => value ? sessionStorage.setItem(tokenKey, value) : sessionStorage.removeItem(tokenKey)
function errorMessage(status: number, data: unknown): string {
  if (status === 413) return '文件超过上传上限（最大 256 MB）。'
  const detail = typeof data === 'object' && data !== null ? (data as { detail?: unknown }).detail : undefined
  const code = typeof detail === 'object' && detail !== null ? (detail as { code?: string }).code : undefined
  const messages: Record<string, string> = {
    identity_required: '请先使用可信身份登录后再上传。',
    identity_not_provisioned: '当前身份尚未开通系统账号。',
    upload_too_large: '文件超过上传上限（最大 256 MB）。',
    invalid_local_credentials: '用户名或密码错误。',
    local_auth_not_configured: '当前部署尚未启用本地账号登录，请使用企业 SSO 或联系部署管理员。',
    evaluation_not_terminal: '任务尚未结束，不能删除。请等待任务完成、失败、取消或超时后再操作。',
    evaluation_flow_not_terminal: '本次评估仍有内部阶段在排队或执行中，暂不能删除。请等待所有阶段结束后再删除整次评估。',
    evaluation_flow_not_found: '评估流程不存在或您无权访问。',
    evaluation_flow_delete_required: '这是评估流程的内部阶段，不能单独删除。请进入“评估流程详情”后删除整次评估。',
    evaluation_has_dependent_tasks: '该评估仍有关联的内部阶段，不能单独删除。请从评估流程详情删除整次评估。',
    x5_evaluation_stage_running: 'X5 评估的板端性能阶段仍在排队或执行中，结束后才能整体删除。',
    evaluated_model_deletion_disabled: '当前系统设置未允许删除已评测模型。',
    model_delete_not_owner: '只能删除自己引用的模型。',
    model_evaluation_not_terminal: '该模型仍有正在执行的评估，请等待结束或取消后再删除。',
    model_asset_not_found: '模型不存在或已被删除。',
    person_has_running_evaluations: '该人员仍有排队或执行中的评估，请先等待结束或取消后再删除。',
    cannot_delete_current_super_admin: '不能删除当前登录的超级管理员。',
    use_super_admin_handover: '超级管理员账号需通过受控交接处理，不能直接删除。',
    platform_migration_too_large: '平台迁移包超过 1 MB 上限。',
    invalid_platform_migration_archive: '迁移包格式无效，只接受系统导出的平台能力 ZIP。',
    platform_migration_catalog_conflict: '目标系统已有同平台和版本但内容不同的 Catalog，已拒绝覆盖。',
    platform_migration_contains_runtime_or_secret: '迁移包包含 Host、运行时或敏感配置，已拒绝导入。',
    super_admin_required: '平台能力包的导入和导出仅允许超级管理员执行。',
    role_forbidden: '当前账号没有此操作权限。',
  }
  return (code && messages[code]) || (typeof detail === 'string' && detail) || (typeof data === 'string' && data) || `请求失败（HTTP ${status}）。`
}
export async function api(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  const token = accessToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  const r = await fetch(base + path, { ...init, headers, credentials: 'same-origin' })
  if (r.status === 204) return undefined
  const isJson = r.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await r.json() : await r.blob()
  if (!r.ok) {
    if (!isJson) {
      await data.text().catch(() => undefined)
      throw new Error(errorMessage(r.status, undefined))
    }
    throw new Error(errorMessage(r.status, data))
  }
  return data
}

/** 管理与 Worker 控制面位于 /api（而非 /api/v1），仍复用当前登录 JWT。 */
export async function controlApi(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  const token = accessToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  const r = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  if (r.status === 204) return undefined
  const isJson = r.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await r.json() : await r.blob()
  if (!r.ok) {
    if (!isJson) throw new Error(errorMessage(r.status, undefined))
    throw new Error(errorMessage(r.status, data))
  }
  return data
}
export const upload = (form: FormData) => api('/model-assets', { method: 'POST', body: form })
export const localLogin = (username: string, password: string) => api('/auth/local/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
})
