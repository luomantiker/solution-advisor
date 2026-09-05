# M0｜生产持久化与 REAL 任务证据基础记录

## 任务目标

在不改变现有 DEMO 可视化闭环的前提下，为控制面建立 SQLite/Local 与 PostgreSQL/MinIO 两种持久化模式、可审查迁移，以及未来 REAL Worker 所需的制品、证据、快照和结果边界。本阶段未启用 REAL 执行。

## 仓库原始状态

- 已有 FastAPI、Vue Portal、SQLite、本地 `data/`、ONNX 内容寻址、DEMO fixture、Mock PDF 和基础 Compose 验收。
- 数据库通过 `Base.metadata.create_all()` 隐式建表；上传文件由业务服务直接写入本地路径；没有 S3、迁移或证据数据模型。
- 本次开始时 `git status --short` 无输出。`docs/promp/` 仅作为本地任务输入，未提交。

## 实际实现

- 配置：`Settings` 读取数据库、存储后端、S3 endpoint/bucket 和自动迁移开关。开发默认 SQLite + Local Storage；生产使用 PostgreSQL + S3-compatible MinIO。
- 迁移：Alembic 迁移 `0001_persistence_foundation`，支持空库建表，并兼容已有 MVP SQLite 表新增列。升级命令为 `uv run alembic upgrade head`；已有 SQLite 文件须先备份，迁移不删除数据，破坏性 downgrade 不提供。
- 存储：`ArtifactStorage` 定义 `put/open/exists/delete`；Local URI 示例为 `file:///…/sha256/ab/<sha256>`，S3 URI 示例为 `s3://solution-advisor/artifacts/sha256/ab/<sha256>`。对象键由 SHA-256 决定，不使用原始文件名作为身份。
- 领域：`Artifact` 只保存 URI、哈希、大小、内容类型、后端、可见性；ONNX/PDF/日志二进制不写入数据库。`Evidence` 通过受控类型、阶段、可见性枚举关联 Artifact/任务/平台/版本。`TaskSnapshot` 在 DEMO 创建时冻结 Asset/Profile、模板和平台包版本。`EvaluationResult` 具有 `source`、Schema 版本、公共/平台结果和证据 ID 边界。
- DEMO：结果 `source=DEMO`，来自版本化 fixture，`evidence_ids=[]`；不会创建 Evidence。`REAL` 可由数据库/schema 表达，但公共创建 API 返回 `422` 和稳定码 `real_mode_not_enabled`。
- Compose：新增 `docker-compose.prod.yml`，运行 `web`、`api`、`migrate`、`postgres`、`minio`。只有 `web` 发布 `8080`；其他服务仅在 Compose 内网。PostgreSQL 和 MinIO 使用命名卷；常规 `down` 不带 `-v`。

## 实际验收

### SQLite / Local

执行 `docker compose up --build -d` 后，`api` 与 `web` 启动，`http://127.0.0.1:8080/api/healthz` 返回 `200`。真实 Chromium 通过 Portal 上传 `tests/fixtures/minimal.onnx`、创建 DEMO、预览报告、下载 Mock PDF；临时证据位于 `/tmp/solution-advisor-m0-local/`，未提交。随后执行 `docker compose down`，保留 `./data/`。

### PostgreSQL / MinIO

执行：

```bash
cp .env.production.example .env.production
docker compose -f docker-compose.prod.yml up --build -d
```

实际状态：`postgres` healthy、`minio` healthy、`migrate` 以退出码 0 完成、`api` 和 `web` Up；宿主机仅有 `0.0.0.0:8080->80`。查询 PostgreSQL 的 `alembic_version` 为 `0001_persistence_foundation`。通过 8080 的真实浏览器上传、DEMO、报告和 PDF 下载成功，临时证据位于 `/tmp/solution-advisor-m0-prod/`。上传 ONNX 和生成 PDF 后，PostgreSQL 查询到 `storage_backend=s3` 的 2 个 Artifact，证明对象未写入数据库。

## 测试、构建与配置

```text
uv run pytest                         13 passed，覆盖率 96.14%
npm --prefix frontend run build       通过（vue-tsc + Vite）
git diff --check                      通过
docker compose config                 通过
docker compose -f docker-compose.prod.yml config 通过
```

单元/契约测试覆盖：空 SQLite 迁移、PostgreSQL/S3 配置解析、Local Storage 内容寻址和元数据去重、Fake S3 URI/读写/删除、Artifact/Evidence/TaskSnapshot/EvaluationResult、DEMO/REAL 隔离，以及既有 API/PDF 回归。

## 已知限制与 M4 前置条件

- PostgreSQL/MinIO 是生产近似 Compose，不包含 TLS、备份任务、密钥管理、监控或高可用。
- `ArtifactStorage.delete` 只提供受控清理接口，未接入自动删除。
- 没有 Worker、SSH、工具链、板卡、编译或性能测试；Evidence 只是未来回传的存储契约。
- 进入 M4 前应具备：生产 Secret/备份策略、对象存储保留策略、REAL 任务权限与 Worker 身份协议、证据上传校验和审计要求；然后才可接入首个 X5 静态检查 Worker。

## 提交与工作区

- 本次主提交信息：`feat(storage): 建立生产持久化与证据基础`；hash 与 push 结果以最终交付回报为准。
- 本记录不提交任务书、`.env.production`、运行时数据、临时截图或 PDF。
