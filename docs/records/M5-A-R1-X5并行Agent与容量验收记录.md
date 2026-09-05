# X5 并行 Agent 执行与真实容量验收记录

日期：2026-08-30

## 目标与边界

本轮将 `x5-j6-host` 从单槽编译升级为经验证的三槽编译执行。容量只适用于固定 X5 编译 Runner；
同一板卡的 `REAL_BOARD_SMOKE` 仍保持单任务互斥，不把板端 Runtime 并发结论外推为编译容量。

## 实施事实

- HostAgent 以 `max_concurrency=3` 登记自身上限；Binding 只能被调整到该登记上限以内。
- 一个编译任务对应一个独立短时 Runner 容器、一个 PostgreSQL `WorkerCapacityLease` 和一个
  `slot_index`；各槽位独立心跳续租，任务结束后独立释放。
- 动态 `PlatformWorker` 的租约已被聚合到 HostAgent 管理视图和“Worker 与租约”明细，避免繁忙
  平台 Worker 被误显示为零运行。
- 同一动态 Worker 存在 `CLAIMED` 或 `RUNNING` 的板端性能任务时，控制面拒绝再 claim 第二个
  `REAL_BOARD_SMOKE`；编译任务仍可使用空闲编译槽位。

## 真实容量证据

使用已完成通用分析的 `googlenet.onnx` Profile，同时创建三项真实 X5 编译任务：

| 任务 | 槽位 | 结果 |
|---|---:|---|
| `task_21620f8cbbea49349701ac5a0241b470` | 0 | `SUCCEEDED`，租约已 `RELEASED` |
| `task_f32e25b849724ac1bfa61f44df0af4fe` | 1 | `SUCCEEDED`，租约已 `RELEASED` |
| `task_8502973befd94a64b1f3b2da8babb10a` | 2 | `SUCCEEDED`，租约已 `RELEASED` |

验收期间观察到三份固定 X5 Runner 短时容器同时存在；控制面租约分别为 0、1、2，三项完成后均以
`RELEASED` 收口。任务本身及其 Artifact / Evidence 保留为审计基线。

## 回归

- `uv run pytest -q`：64 通过，覆盖率达到项目阈值；
- `npm --prefix frontend run build`：通过；
- `git diff --check`：通过；
- `docker compose config`、`docker compose -f docker-compose.prod.yml config`：通过；
- 生产 Compose 已重建，HostAgent 服务为 `active`。

本记录只证明 X5 固定编译链的三槽并行能力；不改变 S100 的 `NOT_READY` 状态，也不证明板端性能、
精度、稳定性、功耗或部署推荐。
