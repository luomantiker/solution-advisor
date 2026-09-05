# Solution Advisor

AI 方案评估与建议专家平台。当前处于第一阶段：提供**平台无关**的 ONNX 模型资产管理与结构分析，为后续多平台评估建立可复用的模型事实基线。界面由 `frontend/` 中的 Vue 3 + TypeScript 应用承载；FastAPI 只提供 API、任务和报告数据。

> 当前版本不连接芯片板卡或 SSH，不执行模型编译或性能测试；Docker 仅用于控制面和本地/生产近似部署。

## 快速入口

| 我想做什么 | 从这里开始 |
|---|---|
| 了解平台整体设计 | [`docs/design/AI方案评估与建议专家平台_设计文档.md`](docs/design/AI方案评估与建议专家平台_设计文档.md) |
| 运行服务或调用接口 | [本地运行](#本地运行) / [API 概览](#api-概览) |
| 执行测试与查看质量门槛 | [测试与 CI](#测试与-ci) |
| 了解第一阶段任务范围 | [`docs/promp/01-可视化MVP与通用ONNX分析.md`](docs/promp/01-可视化MVP与通用ONNX分析.md) |

## 当前状态

| 能力 | 状态 | 说明 |
|---|---|---|
| ONNX 上传、校验与 SHA-256 内容寻址 | 已完成 | 同一内容只保存一份原始文件。 |
| 通用 ONNX Profile | 已完成 | 输出模型结构事实，不输出任意芯片结论。 |
| Profile 缓存 | 已完成 | 缓存键为 `onnx_sha256 + analyzer_version`；版本变化保留旧 Profile 并生成新记录。 |
| REST API、离线 fixture 与自动化测试 | 已完成 | API 和缓存核心路径均有隔离测试覆盖。 |
| 可视 Web Portal 与 DEMO 报告闭环 | 已完成 | 上传、Profile、DEMO 任务、报告预览与 Mock PDF 下载。 |
| GitLab CI | 已配置 | push 与 merge request pipeline 执行全量测试。 |
| 生产持久化基础 | 已完成 | PostgreSQL + MinIO、Alembic 迁移和 Artifact/Evidence 契约。 |
| REAL Worker、真实评测 | 预留 | REAL 仅是受限领域值，公共 API 继续拒绝创建。 |

## 当前能力

- **模型上传**：`POST /api/v1/model-assets` 上传 ONNX 文件，校验通过后按内容 SHA-256 去重存储。
- **通用结构分析**：上传响应返回完整 `profile`（`summary` + 全部 `nodes`），包含 IR 版本、opset、输入/输出张量、节点与算子统计、动态形状 / 控制流 / 外部数据等结构标记。
- **内容寻址复用**：相同模型内容复用同一 Asset 与同一分析器版本的 Profile，并通过 `reused` 标记提示。
- **查询接口**：
  - `GET /api/v1/model-assets/{asset_id}` — 资产摘要与 Profile 概要
  - `GET /api/v1/model-profiles/{profile_id}` — 完整节点清单
  - `GET /healthz` — 健康检查

## 技术选型与原则

Python 3.11+、FastAPI、Pydantic v2（FastAPI 依赖）、SQLAlchemy 2.x、Alembic、SQLite/PostgreSQL、Local/S3-compatible MinIO 与官方 `onnx` 包；依赖由 `pyproject.toml` + `uv` 管理。

- `model_assets/onnx_analyzer.py` 只抽取 ONNX 事实，绝不写入芯片算子支持、风险判断或优化建议。
- 原始模型、SQLite、缓存、虚拟环境与构建产物均不会提交到 Git。
- 测试不依赖外网、Docker、板卡、固定本机目录或执行顺序。

## 目录结构

```text
docs/design/                      # 平台设计文档
src/solution_advisor/
  api/                            # FastAPI API 与路由
  model_assets/                   # 资产上传、内容寻址存储、ONNX 分析
  persistence/                    # SQLite 会话与 ORM
  platforms/ workers/             # 预留模块（本期不实现）
  evaluations/ reports/
tests/                            # pytest 测试与离线 fixture
frontend/                         # Vue 3 + TypeScript Web Portal
```

## 本地运行

前置条件：Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --all-groups
uv run pytest
uv run uvicorn solution_advisor.api.app:app --host 0.0.0.0 --port 8000
npm --prefix frontend ci
npm --prefix frontend run dev
```

也可一键管理本地开发服务：

```bash
./scripts/dev-up.sh
./scripts/dev-down.sh
```

脚本只管理它创建的本地 API（8000）和 Vue Portal（5173）进程，并在被 Git 忽略的 `.run/` 中保存 PID 与日志。

另开终端上传内置的离线测试模型：

```bash
curl -F file=@tests/fixtures/minimal.onnx http://127.0.0.1:8000/api/v1/model-assets
curl http://127.0.0.1:8000/healthz
```

也可用 Compose 以接近发布的形态启动完整控制面（首次复制环境变量示例）：

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs -f
```

开发模式打开 <http://127.0.0.1:5173/> 可使用可视化 DEMO Portal；API 位于 <http://127.0.0.1:8000/>。Compose 模式只发布 <http://127.0.0.1:8080/>：Nginx 提供 Vue SPA，并把 `/api/` 转发给 Compose 内部网络中的 FastAPI（不暴露 API 的 8000 端口）。可用 `docker compose down` 停止容器；`./data/` 是宿主机持久化的运行时数据，停止容器不会删除它。

Compose 发布后可执行以下可重复的浏览器验收；截图和下载的 PDF 默认写入 `/tmp/solution-advisor-compose-smoke/`，不会进入仓库：

```bash
npm --prefix frontend run smoke:compose
```

页面和下载的 PDF 都会标记 `Mock / 不可用于交付结论`。

### 生产近似 Compose：PostgreSQL + MinIO

生产配置不挂载源码或 `data/`，只发布 Web 的 8080 端口；API、PostgreSQL 和 MinIO 都仅在 Compose 内网可见。复制安全示例后替换所有 `change-me` 值：

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl http://127.0.0.1:8080/api/healthz
```

`migrate` 服务在 PostgreSQL 健康后明确执行 `alembic upgrade head`，API 设置为 `SOLUTION_ADVISOR_AUTO_MIGRATE=false`，不会以 `create_all()` 隐式建表。手动升级使用：

```bash
SOLUTION_ADVISOR_DATABASE_URL='postgresql+psycopg://…' uv run alembic upgrade head
```

停止时保留命名卷和数据：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

只有在已验证备份且明确要清空生产数据时才可另行使用 `down -v`；常规停止命令不包含该选项。

## API 概览

| 方法与路径 | 行为 | 成功状态码 |
|---|---|---|
| `POST /api/v1/model-assets` | 上传 `multipart/form-data` 的 `file` 字段，创建或复用 Asset/Profile | `201` |
| `GET /api/v1/model-assets/{asset_id}` | 查询资产与最新 Profile 摘要 | `200` |
| `GET /api/v1/model-profiles/{profile_id}` | 查询完整通用 ONNX 分析结果和节点清单 | `200` |
| `GET /healthz`（开发）/ `GET /api/healthz`（Compose） | 服务健康检查 | `200` |
| `POST /api/v1/evaluation-tasks` | 创建仅限 `DEMO` 的示例多平台任务 | `201` |
| `GET /api/v1/model-assets/{asset_id}/evaluation-tasks` | 查询该模型下自己的历史任务与明确分享给自己的任务 | `200` |
| `GET /api/v1/evaluation-tasks/{task_id}` | 查询任务和示例结果状态 | `200` |
| `GET /api/v1/reports/{task_id}` | 预览统一报告 ViewModel | `200` |
| `GET /api/v1/reports/{task_id}/download` | 下载标有 Mock 提示的 PDF | `200` |
| `GET /api/v1/model-assets/{asset_id}/download` | 下载自己拥有或随评估明确附带的 ONNX 模型 | `200` |
| `POST /api/v1/evaluation-tasks/{task_id}/shares` | 分享单次评估，可选择是否附带 ONNX 模型 | `201` |
| `POST /api/v1/evaluation-task-shares` | 批量分享同一模型下的已完成评估，可选择是否附带 ONNX 模型 | `201` |

上传接口的关键返回字段：

```json
{
  "asset": {"id": "asset_…", "sha256": "…", "size_bytes": 123},
  "profile": {"id": "profile_…", "analyzer_version": "1.0.0", "summary": {}, "nodes": []},
  "reused": {"asset": false, "profile": false}
}
```

错误语义：缺少 `file` 字段返回 `400`；无法解析或校验的 ONNX 返回 `422`；不存在的 Asset/Profile 返回 `404`。错误响应不暴露本机路径和堆栈。

## 配置

部署人员应先阅读 [配置文件与优先级说明](docs/operations/配置文件与优先级说明.md)：它说明需要维护的
环境变量、HostAgent、板端 Profile 文件及其覆盖优先级。企业 SSO 和本地账号的启用条件也在该文档中。
普通用户查看历史评估、下载 PDF 及共享资源的规则见
[用户模型评估与共享](docs/operations/用户模型评估与共享.md)。

运行时可设置以下环境变量改变运行时文件位置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SOLUTION_ADVISOR_DATABASE_URL` | `sqlite:///data/solution-advisor.sqlite3` | SQLite 数据库位置 |
| `SOLUTION_ADVISOR_STORAGE_ROOT` | `data/uploads` | 内容寻址文件存储目录 |
| `SOLUTION_ADVISOR_STORAGE_BACKEND` | `local` | `local` 或 `s3`。 |
| `SOLUTION_ADVISOR_S3_BUCKET` | `solution-advisor` | S3/MinIO bucket 名称。 |
| `SOLUTION_ADVISOR_S3_ENDPOINT_URL` | 空 | MinIO/S3 endpoint，例如 `http://minio:9000`。 |
| `SOLUTION_ADVISOR_AUTO_MIGRATE` | `true` | 开发 SQLite 默认自动迁移；生产必须为 `false`，由 migrate 服务执行。 |

## 测试与 CI

- 本地：`uv run pytest`（覆盖率门槛 80%，见 `pyproject.toml`）。
- 迁移：`uv run alembic upgrade head`；当前迁移版本为 `0001_persistence_foundation`。已有 SQLite 文件升级前应先备份其 `.sqlite3` 文件；迁移不会删除运行时数据，也不提供破坏性 downgrade。
- CI：`.gitlab-ci.yml` 在 GitLab 的 push 与 merge request pipeline 中执行空 SQLite 迁移、全量测试和前端构建。
- 测试 fixture 使用临时 SQLite 与临时文件目录，无外网、Docker、板卡或固定路径依赖。

提交前建议执行：

```bash
uv sync --all-extras
uv run pytest
git diff --check
```

## 架构边界与下一步

`Artifact` 只记录对象 URI、SHA-256、大小和内容类型；二进制 ONNX/PDF/日志不写入数据库。`Evidence` 是未来真实日志、编译产物和板端输出的受控索引，当前 DEMO fixture 绝不创建 Evidence。`TaskSnapshot` 冻结模型/Profile/模板/平台包版本，`EvaluationResult` 预留公共结果、平台结果、证据引用和 Schema 版本。`platforms/` 与 `workers/` 仍仅为预留模块，不创建真实 Docker/板卡连接，也不编译或执行真实性能评测。

下一阶段应先定义 `PlatformPackage` 的版本化规则包与 `EvaluationTask` / `EvaluationResult` 领域模型，再接入受控的 WorkerRuntimeManager。平台特定规则必须消费通用 `ModelProfile`，不能反向污染 ONNX 分析器。整体演进路线见 [`docs/design/AI方案评估与建议专家平台_设计文档.md`](docs/design/AI方案评估与建议专家平台_设计文档.md)。

## 贡献约定

新增能力必须同时提供隔离测试，并更新对应任务文档的“新增/调整测试”“全量回归命令”“验收结果”小节。请勿提交 `data/` 下运行时数据、上传模型、SQLite 数据库、缓存或虚拟环境。
