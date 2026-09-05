# M0 Compose 发布闭环与可视化验收记录

## 任务目标

验证既有 M1--M3 可视化 MVP 能够以 Compose 的发布形态运行。范围限于控制面、Vue Portal、Nginx 反向代理、DEMO fixture 与 Mock PDF；未新增 REAL Worker、板卡、SSH、工具链、编译或性能测试。

## 仓库原始状态

- 已有 FastAPI、SQLite、ONNX 通用分析、Vue Portal、DEMO 任务和 Mock PDF 闭环。
- Compose 已定义 `api` 和 `web` 两个服务，但 Nginx 未声明静态站点根目录，访问 `/` 和 SPA 深链接会发生 `/index.html` 内部重定向循环；后端也仅提供 `/healthz`，不满足 Compose 入口的 `/api/healthz`。
- 本次验收开始前工作区只有本地任务书；按仓库约定已忽略 `docs/promp/`，未将任务书纳入本次提交。

## 实际新增与修改

- `docker-compose.yml`：API 仅暴露到 Compose 内部网络，宿主机只发布 Portal 的 `8080`。
- `frontend/nginx.conf`：声明静态站点 `root` 与 `index`，修复首页和 SPA 深链接。
- `src/solution_advisor/api/app.py`、`tests/test_model_assets.py`：增加 Compose 代理健康检查 `GET /api/healthz`，并保留开发模式 `GET /healthz`。
- `frontend/scripts/compose-smoke.mjs`、`frontend/package*.json`：增加 Playwright 驱动的真实浏览器验收和可重复的 `npm --prefix frontend run smoke:compose` 命令。
- `src/solution_advisor/reports/service.py`、`tests/test_demo_evaluations.py`：将 PDF 固定结构补齐为“版本与证据附录”，并校验所有固定章节及禁用交付性措辞。
- `README.md`：明确开发模式、Compose 模式、启动/停止、内网 API 代理和验收命令。

## 已完成能力与访问方式

| 模式 | 入口 | 用途 |
|---|---|---|
| 开发 | `http://127.0.0.1:5173/` | Vite Vue 开发服务器，代理 `/api` 到本机 FastAPI。 |
| 开发 | `http://127.0.0.1:8000/` | FastAPI 直接 API；健康检查为 `/healthz`。 |
| Compose | `http://127.0.0.1:8080/` | Nginx 提供 SPA，并在 Compose 内网代理 `/api/` 到 FastAPI；健康检查为 `/api/healthz`。 |

Compose 启动命令：

```bash
docker compose up --build -d
```

DEMO 验收操作路径：`/` 上传 `tests/fixtures/minimal.onnx` → Model Profile → 创建 DEMO 任务 → DEMO 任务详情与报告预览 → 下载 Mock PDF。

## 浏览器、HTTP、PDF 与日志验收

- 实际执行 `docker compose up --build -d`；`api`、`web` 均为 `Up`，仅 `web` 映射 `0.0.0.0:8080->80`，`api` 为 Compose 内部 `8000/tcp`。
- `GET http://127.0.0.1:8080/`、`GET /models/deep-link-smoke` 均返回 SPA 入口 `200`；`GET /api/healthz` 返回 `200 {"status":"ok"}`。
- Playwright 在真实 Chromium 中验证首页不为空、上传、Profile、DEMO 任务、报告预览和 PDF 下载；验收截图（临时、不提交）位于 `/tmp/solution-advisor-m0/home.png`、`profile.png`、`task-report.png`。
- Mock PDF 为 `/tmp/solution-advisor-m0/report.pdf`；`pypdf` 成功提取 1 页、369 个字符，包含 5 个固定章节和 `Mock / 不可用于交付结论`，且不包含“推荐部署”“已实测”。`pdftoppm` 成功渲染为 `/tmp/solution-advisor-m0/report-render.png`，人工检查文本清晰可读。
- `docker compose logs` 最终验收请求均为 `200/201`；容器重建瞬间的历史 `502` 不作为最终验收结果，重建完成后浏览器验收全程成功。

## 自动化测试、构建与配置验收

执行于最终提交前：

```bash
uv sync --all-extras
uv run pytest
npm --prefix frontend run build
git diff --check
docker compose config
docker compose up --build -d
npm --prefix frontend run smoke:compose
```

结果：通过（pytest 8 项，覆盖率不低于项目门槛 80%；Vue 类型检查与 Vite 构建成功；Compose 配置有效；真实容器和浏览器验收成功）。

## 与设计的差异

- 没有引入 PostgreSQL、Redis、MinIO/NAS 或任何 REAL Worker；M0 只验证当前 SQLite/本地持久化 DEMO 控制面的发布闭环。
- 浏览器验收工具采用 Playwright，仅作为前端开发依赖和可重复验收脚本，不进入运行时镜像。

## 已知限制

- Compose 的 `./data/` 为本机 bind mount，适合 MVP 持久化，不是生产级对象存储或数据库方案。
- API 没有在 Compose 下直接发布到宿主机；需要调 API 时经 `http://127.0.0.1:8080/api/...`。
- 所有任务和报告均是版本化 fixture 产生的 DEMO/Mock，不可用于交付结论。

## 下一步建议

先定义生产部署所需的配置、密钥、数据库迁移与对象存储策略；随后在独立、受控的 Worker 边界中设计 REAL 任务状态和证据采集，且在具备真实工具链与板卡环境前不生成真实性能或部署结论。

## 提交后记录

- 本次提交信息：`test(deploy): 完成Compose发布闭环验收`；提交 hash 以仓库 Git 日志和交付回报为准。
- 提交前 `git diff --cached --stat`：11 files changed, 213 insertions(+), 8 deletions(-)。
- 提交前 `git status --short`：`README.md`、`docker-compose.yml`、`frontend/nginx.conf`、`frontend/package*.json`、`src/solution_advisor/api/app.py`、`src/solution_advisor/reports/service.py`、两份测试文件为修改；本验收记录和 `frontend/scripts/compose-smoke.mjs` 为新增。所有文件均已显式暂存；没有暂存 `docs/promp/` 或运行时产物。
