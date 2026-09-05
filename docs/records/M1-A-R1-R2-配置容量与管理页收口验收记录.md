# M1-A-R1-R2：配置草稿、容量竞争与管理页验收记录

## 目标与范围

收口 M1-A-R1 遗留的持久化草稿、配置发布闭环、common-analyzer 容量租约和管理页操作能力。本阶段没有接入 X5 工具链、Docker load、模型编译、板卡/SSH，也不创建 REAL 任务。

## 已实现能力

- `0004_drafts_capacity_r2` 新增 `AnalyzerConfigDraft`，保存基线版本、完整受限内容、哈希、Schema 版本、操作者、时间、状态与说明。
- 草稿支持创建、读取、编辑、校验、丢弃、乐观并发发布及从历史版本创建并发布回滚；审计覆盖成功、校验失败和版本冲突。
- common-analyzer 只读取活动配置；分析任务创建时在事务中冻结配置快照。
- PostgreSQL 租约以活跃槽位部分唯一索引和活动配置行锁保护，持久化槽位、任务、attempt、心跳、过期和终态；释放幂等，恢复器可回收过期租约并重新排队。
- `/admin` 使用 sessionStorage 会话、中文错误恢复提示和四个操作区：当前配置、草稿编辑、历史/审计、Worker/租约；不以原始 JSON 作为界面，也不展示 Token。

## API 与浏览器访问

管理 API：`/api/admin/analyzer-config`、`/history`、`/drafts` 和 `/api/admin/worker-instances`。浏览器从 `http://127.0.0.1:8080/admin` 输入管理员 Token 后：创建草稿、编辑受限模块、保存、确认发布；在历史页执行二次确认回滚；Worker 页查看容量与脱敏租约。临时截图只用于本地验收，不提交。

## 自动化与容器验收

执行结果：`uv run pytest` 为 **17 passed**，覆盖率 **89.00%**；`npm --prefix frontend run build` 成功；`git diff --check` 成功；两个 Compose 配置校验成功；`docker compose -f docker-compose.prod.yml up --build -d` 成功，migrate 成功退出，API、Web、PostgreSQL、MinIO、Redis、common-analyzer 均健康/运行。

`npm --prefix frontend run smoke:compose` 成功完成 `8080` 上的上传 → 异步 Profile → DEMO → 报告 → Mock PDF 下载。Playwright 无头浏览器验证了 `/admin` 未授权入口、授权、退出前的当前配置/草稿创建/历史/Worker 区域，临时截图写入 `/tmp/solution-advisor-r2-admin.png` 且未提交。Token 不在 URL 或 localStorage 中。

PostgreSQL 容器内以 6 个并发请求竞争 `max_concurrency=2` 的 common-analyzer：`granted=2, active=2, bounded=True`；临时租约已幂等释放。测试覆盖草稿全生命周期、未授权/错误 Token、版本冲突、非法配置、槽位上限/释放/过期回收、Worker BUSY 语义以及既有 ONNX/DEMO/PDF 回归。

## 边界与后续

本记录不表示 X5 可编译或板卡可用：M4-A 才实现 X5 平台 Runner、受控编译与真实 Artifact/Evidence，M4-B 才实现板卡连接和真实性能证据。进入 M4-A 前须具备经审查镜像清单、平台 Runner 契约、Worker Host 注册/身份和 PostgreSQL/对象存储/Redis 的生产联调环境。
