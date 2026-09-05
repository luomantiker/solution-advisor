# M5-A-R1：Candidate 接入工作区与真实验证门禁验收记录

## 结论与当前快照（2026-08-31）

Candidate 已收口为受控接入工作区。离线契约检查不再能使 Candidate 直接进入审核目录；只有当前
revision 的固定真实接入 Runner 产出 `SUCCEEDED` Evidence，才允许生成待审核 Catalog。`PENDING_INTEGRATION`
Catalog 继续显示在“接入中”，不会被错误展示为“已接入”。

本记录完成后 S100 曾按当时治理状态完全重置；目前已重新创建新的 `S100 / 3.7.0` Candidate，仍处于
`PENDING_INTEGRATION`，尚未创建 Catalog、Binding 或 Worker。该 Candidate 已完成当前修订的步骤 2
离线契约检查，步骤 3 因未安装经审核的 S100 固定真实接入 Runner 而如实为 `BLOCKED`。这不表示 S100
已完成真实接入。

## 工作流与安全边界

```text
发现镜像 → Candidate 工作区（资料/固定命令模板） → 离线契约检查
→ 固定真实 Runner 验证（Artifact / Evidence） → 待审核 Catalog
→ 审核发布 AVAILABLE → Binding / READY Worker → 用户可选平台
```

- 工作区仅保存显示名、接入档案说明、固定编译命令模板和固定板端验证命令模板；不填写内部 Profile ID，
  不提供 Shell、Docker 参数、路径或凭据字段。模板只能使用系统授权占位符，完整说明见
  [平台接入与扩展手册](../design/平台接入与扩展手册.md) 的“系统授权占位符与固定命令模板”。
- 每次保存工作区都更新 Candidate revision，旧的步骤 2 离线检查和步骤 3 真实验证均不再适用。
- 步骤 3 必须以前一当前 revision 的步骤 2 已通过为前提；前端会禁用步骤 3，后端也会拒绝绕过步骤 2 的请求。
- 未安装固定 Runner 时，真实验证写入 `BLOCKED` Artifact/Evidence，原因是
  `real_validation_runner_not_installed`；不执行容器、编译或板端命令，也不伪造通过。
- `manifest.json` 与 `runner.json` 可在工作区查看其受控 Package 结构；这不是 Host 文件系统浏览能力。

## S100 当前状态

S100 仍处于 M5-A-R0 的 `NOT_READY` 基线：虽已声明候选编译入口和板端性能入口，但尚未交付并审核
固定 Runner、实际产物格式、Runtime/输出契约和版本化 fixture。因此 S100 的真实验证应如实 `BLOCKED`，
不能生成 Catalog，更不能创建 Binding、Worker 或作为用户评估可选平台。

`s100-3-7-0-eb401fa186f8` 曾在旧离线检查逻辑下错误发布。经超级管理员确认后，已于
2026-08-30 完全重置其平台治理注册：删除 S100 的 PlatformType、Candidate、Catalog、CandidateHistory、
PlatformAudit、两条 S100 Evidence 和独有 Candidate Package Artifact。HostAgent 对相同 immutable digest
的只读镜像发现记录保留，因此该镜像回到 `DISCOVERED`，可从“创建 Candidate”重新开始。

重置后，管理员已从该已发现镜像重新创建新的 S100 Candidate，并登记：

| 项目 | 当前状态 |
| --- | --- |
| 平台类型 / 目标版本 | `S100 / 3.7.0` |
| Candidate | `PENDING_INTEGRATION`，由超级管理员认领 |
| 步骤 1 | 已保存编译模板 `hb_compile --fast-perf --march nash-e --model {model}` 与板端模板 `hrt_model_exec perf --model_file {model} --profile_path {profile_dir}`；两者均为声明，未实测 |
| 步骤 2 | 已通过当前 revision 的离线 Package、镜像锁与 Runner 契约检查 |
| 步骤 3 | `BLOCKED`：`real_validation_runner_not_installed`；未执行 S100 编译、容器或板端命令 |
| Catalog / Binding / Worker | 均未创建；用户不可选择 S100 |

删除前确认没有 S100 Binding、Worker 或评估任务。离线测试结果 Artifact 同时被两条 J6 Evidence 引用，
因此按引用完整性保留该共享 Artifact 与 J6 Evidence；X5 Catalog、Binding、Worker、任务、制品和 Evidence
均未触碰。

## 验收

| 检查 | 结果 |
| --- | --- |
| Candidate 工作区、revision 失效、真实验证受阻与步骤顺序定向测试 | 通过 |
| `uv run pytest -q tests/test_platform_governance.py --no-cov` | 23 passed |
| `uv run pytest -q --no-cov` | 69 passed |
| `npm --prefix frontend run build` | 通过 |
| `git diff --check` | 通过 |
| `docker compose config` 与生产 Compose config | 通过 |
| `docker compose -f docker-compose.prod.yml up --build -d` | 当前代码已完成 Compose 重建并通过 Web 就绪检查；本次仅更新验收文档，未重复部署 |
| 本地超级管理员会话 HTTP 验收 | 已验收：X5 为“已接入”；S100 Candidate 为“接入中”，且步骤 3 明确显示受阻原因 |
