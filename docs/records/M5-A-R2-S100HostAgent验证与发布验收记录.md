# M5-A-R2：S100 HostAgent 验证与发布验收记录

## 实施状态

- 已实现 Candidate revision 绑定的 `CandidateValidationTask`，支持排队、领取、开始、Evidence 回传、完成、幂等活动任务和失败后重试。
- 已实现 S100 专属 `.hbm / s100_hbm`、`s100-hrt-profile-1.0`、11 类 Evidence 白名单及 MinIO Artifact 上传接口。
- 已实现 S100 固定 HostAgent 执行器和私有安装说明；不接受网页命令、Docker 参数、SSH、板端地址、凭据或路径。
- Catalog 草稿门禁要求当前 revision、成功系统验证及 Evidence；人工 M5-A-R1 日志和产物不作为通过输入。

## 已完成的真实验证（2026-08-30）

- 受保护 Host 私有目录、Token、known_hosts、板端 profile 和独立工作目录已安装；普通用户读取私有配置被操作系统拒绝，服务身份可正常执行。
- Candidate `candidate_0ab662f777cf425dab1a508009ca46fa` 当前 revision `20` 的第二次系统验证任务 `candidate_validation_ed3ca2470292455fbe30c412a1536b74` 为 `SUCCEEDED`；第一次任务因 Agent 未递归定位固定 Runner 的嵌套 `.hbm` 输出而 `BLOCKED`，其 4 项编译 Evidence 被保留。
- 本轮成功任务实际生成 `model.hbm`（`s100_hbm`，SHA256 `81c15d9935d317a9cb2e35932a43688214525bf27866493179290b2612f209a4`，35552 bytes），板端 `hrt_model_exec perf` 解析为平均 `0.32706 ms`、`2782.105469 FPS`；仅代表 16×16 固定 fixture。
- MinIO Evidence 共 11 项。其中制品 URI 为 `s3://solution-advisor/artifacts/sha256/81/81c15d9935d317a9cb2e35932a43688214525bf27866493179290b2612f209a4`；编译日志、Runner 结果、预检、下发、调用日志、`profiler.log`、`profiler.csv` 与板端结果均已用各自 SHA256 入库。
- 已由管理员审核发布 `S100 / 3.7.0` Catalog；在同一 digest 的 Host 建立 `binding_88aea8918d8b4fe689271961455a6af2`，状态 `HEALTHY`，并创建 1 个 `READY Worker`。

## 验证结果与后续用户侧闭环

本轮代码回归已执行 `uv run pytest -q`、前端 build、`git diff --check`、两套 Compose config 与生产 Compose build/up。M5-A-R1 的人工事实仍仅为基线。

本记录只证明 M5-A-R2 的 **Candidate 系统验证与首次 Catalog/Binding/Worker 发布闭环**。后续
M5-A-R2-R1 已实现用户侧 `EvaluationFlow`、X5/S100 两阶段汇总、Flow 报告与 PDF；新发布的
S100 Release 为 `3.7.0-r1`，其 `s100-runner-1.0.0` 与 Binding/Worker 快照须以 R2-R1 记录为准。

截至 2026-09-01，R2-R1 的普通用户实测发现板端 SSH 身份验证失败，因而该轮新 Flow 的板端阶段真实
失败并保留 Evidence；这不能由本记录中的旧 Candidate 验证 Evidence 补替。详见
[M5-A-R2-R1-S100用户评估与发布收口验收记录.md](M5-A-R2-R1-S100用户评估与发布收口验收记录.md)。
输出一致性、任务精度、稳定性、功耗与部署推荐仍为未验证。
