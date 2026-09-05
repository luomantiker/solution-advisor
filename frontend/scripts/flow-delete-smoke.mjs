import { chromium } from '@playwright/test'

// Browser regression for the user-visible deletion boundary.  The API is
// mocked deliberately: it validates the built Vue route and its requests,
// while Python tests validate the real API/database cascade separately.
const baseUrl = process.env.FLOW_SMOKE_BASE_URL ?? 'http://127.0.0.1:8080'
const assetId = 'asset_flow_smoke'
const flowId = 'flow_done_smoke'
let deleted = false
let deleteRequests = 0

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
await page.route('**/api/v1/**', async route => {
  const request = route.request()
  const url = new URL(request.url())
  const respond = value => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
  if (url.pathname === `/api/v1/model-assets/${assetId}`) {
    return respond({ id: assetId, original_filename: 'flow-smoke.onnx', sha256: 'a'.repeat(64), size_bytes: 16,
      access: 'OWNER', can_download_model: true, can_create_task: true,
      profile: { id: 'profile_flow_smoke', analyzer_version: 'test', summary: { node_count: 1, operator_counts: {} } } })
  }
  if (url.pathname === `/api/v1/model-assets/${assetId}/evaluation-tasks`) {
    return respond(deleted ? [] : [{ id: flowId, resource_kind: 'FLOW', mode: 'REAL', platforms: ['X5', 'S100'],
      progress: { completed: true, percent: 100, label: '评估完成（所有平台）' }, source: 'REAL', access: 'OWNER',
      created_at: '2026-08-31T00:00:00', can_share: false, can_delete: true,
      workflow: { stages: [{ name: 'X5_COMPILE', status: 'SUCCEEDED' }, { name: 'S100_BOARD_PERF', status: 'SUCCEEDED' }] } }])
  }
  if (url.pathname === `/api/v1/evaluation-flows/${flowId}` && request.method() === 'DELETE') {
    deleted = true; deleteRequests += 1
    return route.fulfill({ status: 204 })
  }
  return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'unexpected_smoke_request' } }) })
})

try {
  await page.goto(`${baseUrl}/models/${assetId}`, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: '模型与评估报告' }).waitFor()
  await page.getByText(flowId, { exact: true }).waitFor()
  await page.getByText('task_internal', { exact: true }).count().then(count => {
    if (count) throw new Error('模型列表错误展示了内部阶段')
  })
  await page.getByRole('button', { name: '删除评估' }).click()
  await page.getByText('永久删除本次评估流程', { exact: false }).waitFor()
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.getByText('该模型暂无可查看的评估报告。').waitFor()
  if (deleteRequests !== 1) throw new Error(`期望一次 Flow 删除请求，实际 ${deleteRequests} 次`)
  console.log(JSON.stringify({ baseUrl, flowId, deleteRequests, result: 'passed' }))
} finally {
  await browser.close()
}
