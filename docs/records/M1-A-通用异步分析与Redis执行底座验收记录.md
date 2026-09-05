# M1-A 通用异步分析与 Redis 执行底座验收记录

实现内容：流式临时接收与大小限制、SHA256 内容去重、PostgreSQL `analysis_tasks`/`analysis_events` 事实状态、Redis 队列、独立 common-analyzer 镜像/Runner、配置快照、受保护的管理/容量接口和 Vue 管理页。DEMO 仍是 fixture，REAL API 仍被拒绝。

迁移为 `0002_async_analysis`。实际验收命令和最终 Compose/浏览器结果见交付回报；临时文件、`.env.production`、任务书和 Secret 均不提交。
