# M4-C-R1 平台目录、纳管 Binding 与动态 Worker 分层验收记录

## 目标与迁移映射

本轮将既有单实例 `x5-a` 改造为固定拓扑：

```text
旧 WorkerInstance(x5-a)
  → Agent(x5-a)
  → PlatformBinding(x5-a, X5, catalog_x5_1_0_0)
  → PlatformWorker(worker_x5_a_x5_0)
  → 锁定 X5 platform_runner / 镜像锁
```

迁移 `0008_platform_catalog_bindings` 创建审核后的 `X5 / 1.0.0` Catalog，并把历史 X5
任务、租约和 `TaskSnapshot.platform_governance` 关联到 Catalog、Binding、动态 Worker、Runner、
镜像锁和 `x5-hrt-profile-1.0`。未重跑编译或板卡。

## 已实现能力

- PlatformCatalog 生命周期：候选镜像、`PENDING_INTEGRATION`、`AVAILABLE`、`REJECTED`、
  `SUSPENDED`；发布前校验平台包、镜像锁、Runner、自检、离线测试和审核记录。
- Agent 只经 Worker Token 上报只读候选镜像/工具版本、注册和心跳；候选不会自动发布 Catalog、
  Binding 或 Worker。
- 管理员创建 Binding；健康 Binding 创建/复用动态 Worker。REAL 可调度条件严格为
  `AVAILABLE + HEALTHY Binding + READY Worker`。
- 动态 Worker 与既有 PostgreSQL `worker_capacity_leases` 使用同一事务与槽位协议；任务完成、
  失败、取消、超时后恢复为 READY。
- REAL TaskSnapshot 和报告显示平台治理快照；既有 M4-A `model.bin`、M4-B-R0 板端 Evidence、
  profile 性能解析均保持可查。

## 真实 Compose 验收

生产近似 Compose 已真实执行 `up --build -d` 并运行迁移。迁移后查询结果：

| 实体 | 实际值 |
|---|---|
| Catalog | `X5 / 1.0.0 / AVAILABLE` |
| Binding | `x5-a / X5 / HEALTHY` |
| Worker | `worker_x5_a_x5_0 / READY / runner 1.0.0` |
| 可调度性 | `true` |
| 历史编译快照 | `catalog_x5_1_0_0`、`binding_x5_a_x5_1_0_0`、`worker_x5_a_x5_0` |

原 M4-A 编译任务 `task_44a72342a2834f06b7e80ffb2f27f716` 与 M4-B-R0 板端任务
`task_e561deb2ac2947c49fdfd215be93f522` 仍可查询。后者保留 `model.bin`、板端预检/调用
Evidence、`x5-hrt-profile-1.0`、FPS/Latency 和 CPU 算子分配边界。

暂停 Catalog 或 Binding 后，新的 REAL 创建会被后端拒绝；已有任务、报告、PDF、Artifact 和
Evidence 仍可读。验收中恢复为 `AVAILABLE`，未影响运行环境。

实际暂停验收：对 `catalog_x5_1_0_0` 执行 `SUSPENDED` 后，创建 REAL 编译任务返回
`422 x5_not_schedulable_catalog_suspended`；原板端任务
`task_e561deb2ac2947c49fdfd215be93f522` 的报告 API 仍返回 `200`。恢复为 `AVAILABLE` 后，
目录接口返回 `schedulable=true`。

## 测试与页面

- 自动化覆盖候选不自动纳管、待接入发布前置条件、Binding/READY Worker 可调度性、暂停拒绝、
  X5 REAL 快照，以及 M4-A/M4-B-R0/DEMO 既有回归。
- 管理页增加“平台目录与纳管”，展示候选、Catalog 状态/审核资料、Binding 健康、动态 Worker、
  容量和可调度原因；任务报告展示治理快照。
- 已执行 `uv run pytest -q`：`36 passed`，总覆盖率 `84.92%`（高于 80% 门槛）；
  `npm --prefix frontend run build` 通过；`git diff --check`、两份 Compose 配置检查通过。
- 已执行 `docker compose -f docker-compose.prod.yml up --build -d`。`/api/healthz` 返回
  `{"status":"ok"}`；生产近似容器中的 PostgreSQL、MinIO、Redis、API、common-analyzer 和 Web
  均正常运行。
- 浏览器经 `http://127.0.0.1:8080` 实测未授权入口、管理员授权后的“平台目录与纳管”、模型
  Profile 页、板端任务/报告页均非空白且正常渲染；Token 不在 URL 或 `localStorage` 中。
- 下载的历史板端 PDF 保存为临时文件 `/tmp/solution-advisor-m4c-real-board.pdf`，`pdftotext`
  可提取“平台目录与执行快照”“X5”“NOT_VERIFIED”，并按 PDF 单页渲染验证可读。临时截图和 PDF
  仅作验收证据，未提交。

## 边界与下一步

本轮不新增平台、不运行 `docker load`、不重跑板卡、不新增精度、稳定性、功耗或性能测试；
不接受任意 Shell、Docker 参数、挂载、网络、路径或凭据。下一阶段精度验证需要版本化输入样本、
输出 dump、比较规则及其 Artifact/Evidence 契约。
