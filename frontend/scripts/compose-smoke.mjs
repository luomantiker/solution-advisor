import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const baseUrl = process.env.COMPOSE_BASE_URL ?? 'http://127.0.0.1:8080'
const artifactDir = process.env.SMOKE_ARTIFACT_DIR ?? '/tmp/solution-advisor-compose-smoke'
const fixturePath = path.resolve(process.cwd(), '../tests/fixtures/minimal.onnx')

await mkdir(artifactDir, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()

try {
  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: '上传 ONNX' }).waitFor()
  await page.screenshot({ path: path.join(artifactDir, 'home.png'), fullPage: true })

  await page.locator('input[type="file"]').setInputFiles(fixturePath)
  await page.getByRole('button', { name: '上传并分析' }).click()
  await page.waitForURL(/\/models\/asset_/, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Model Profile' }).waitFor()
  await page.screenshot({ path: path.join(artifactDir, 'profile.png'), fullPage: true })

  await page.getByRole('link', { name: '创建 DEMO 任务' }).click()
  await page.waitForURL(/\/tasks\/new\?profile_id=/, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: '创建 DEMO 多平台任务' }).waitFor()
  await page.getByRole('button', { name: '创建 DEMO 任务' }).click()
  await page.waitForURL(/\/tasks\/task_/, { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'DEMO 任务详情与报告预览' }).waitFor()
  await page.getByText('Mock / 不可用于交付结论', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(artifactDir, 'task-report.png'), fullPage: true })

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: '下载 Mock PDF' }).click(),
  ])
  const pdfPath = path.join(artifactDir, 'report.pdf')
  await download.saveAs(pdfPath)
  console.log(JSON.stringify({ baseUrl, artifactDir, assetUrl: page.url(), pdfPath }))
} finally {
  await browser.close()
}
