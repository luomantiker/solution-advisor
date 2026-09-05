# 平台治理工作台 Session 交接记录

## 当前目标

完成“平台治理工作台”：HostAgent 持续运行、只读发现 Docker 镜像；管理员将纯镜像转为
PlatformCandidate，生成候选 Package、执行受控接入测试并审核发布 Catalog；Catalog 是跨 Host
平台资产，后续 Host 以相同 immutable digest 建立 Binding/Worker 后复用。

## 代码与运行上下文

| 范围 | 入口/事实 |
| --- | --- |
| 后端 | `src/solution_advisor/platforms/domain.py`、`service.py`、`api/routers/platforms.py` |
| HostAgent | `workers/worker_agent.py`；安装器 `workers/host_agent_install.py`；wheel entry point 在 `pyproject.toml` |
| 前端 | `frontend/src/pages/AdminPage.vue`；路由 `/admin`；Token 仅 `sessionStorage` |
| 数据库 | `0008_platform_catalog_bindings`、`0009_host_images`；PostgreSQL 为生产事实来源 |
| 部署 | production Compose 仅暴露 `http://127.0.0.1:8080`；API/Redis/PG/MinIO 为内部服务 |
| 实机 Agent | `x5-j6-host`，配置 `/etc/solution-advisor/host_agent/config.yaml`，systemd service `solution-advisor-host-agent.service` |

## 数据模型与状态机

```text
HostAgent 1—N HostImage (DISCOVERED)
HostImage —管理员创建→ PlatformCandidate (PENDING_INTEGRATION)
PlatformCandidate —测试/审核→ PlatformCatalog (AVAILABLE | REJECTED | SUSPENDED)
HostAgent + PlatformCatalog（digest 一致）→ PlatformBinding (HEALTHY | OFFLINE | SUSPENDED)
PlatformBinding → PlatformWorker (READY | BUSY | DRAINING | ERROR | OFFLINE) → 固定 Runner
```

`TaskSnapshot` 冻结 Catalog/Binding/Worker/Runner/镜像锁；Artifact/Evidence 文件存对象存储，数据库只存 URI、哈希、类型、元数据。

## API 与权限

| API | 用途 |
| --- | --- |
| `GET /api/admin/host-images` | 三态来源；管理员 Token |
| `POST /api/admin/host-images/{id}/platform-candidates` | 纯镜像创建 Candidate；受限 package_id；管理员 Token |
| `GET /api/admin/platform-candidates` | 接入中对象 |
| `GET/POST /api/admin/platform-catalogs`、`/{id}/publish`、`/{id}/state` | Catalog 审核发布/暂停 |
| `GET/POST /api/admin/platform-bindings` | 纳管；必须本 Host 已发现 Catalog digest |
| `GET /api/admin/platform-workers` | 容量与执行状态 |

未授权不得读取写入；稳定错误包括 `catalog_image_not_discovered_on_host`、`platform_candidate_exists`。禁止 Token 出现在 URL/localStorage/日志。

## 前端实施规格

`AdminPage` 必须保留现有“当前配置、草稿、历史、Worker 与 REAL 任务”功能。仅重构 `platforms` 区：

1. 顶部 HostAgent 概览卡；
2. 三列/三组镜像：DISCOVERED 灰蓝 `○`、INTEGRATING 琥珀 `◐`、MANAGED 绿色 `●`；
3. DISCOVERED 使用弹窗/抽屉输入 package_id、说明，调用 Candidate API；
4. Candidate 显示 Package、镜像锁、测试/审核缺项；
5. Catalog 显示跨 Host 复用关系；Binding/Worker 显示容量和原因；
6. 所有空、加载、401/403、网络失败均中文且可恢复；正常主体不显示 JSON。

## Candidate Package 与接入测试的待定实现

当前 API 在控制面运行目录写候选 Package 骨架，不适合作为生产持久化方案。改造方向：生成版本化 Artifact 或由 HostAgent 在固定受控工作目录生成；输出 manifest、image.lock、固定 Runner、self-check、offline-test、结果 Evidence。Candidate 测试只能使用白名单 Runner；审核通过才允许创建 Catalog，之后才 Binding/Worker。不得把 Candidate Runner 当正式 Worker。

## 跨 Host 验收矩阵

| 情形 | 预期 |
| --- | --- |
| A 发现 D，完成 Catalog | A 可 Binding；Catalog 为全局资产 |
| B 发现同一 D | B 可复用 Catalog，创建自己的 Binding/Worker |
| B 未发现 D | Binding 拒绝 `catalog_image_not_discovered_on_host` |
| A/B tag 相同但 digest 不同 | 不可复用 |
| Catalog 暂停 | 禁止新 REAL，历史任务/Evidence/PDF 可读 |

## 验收命令

```bash
uv run pytest -q
npm --prefix frontend run build
git diff --check
docker compose config
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml up --build -d
systemctl is-active solution-advisor-host-agent.service
systemctl is-enabled solution-advisor-host-agent.service
```

## 已完成

- M4-A/M4-B/R1 既有 X5 REAL 编译、板端冒烟、profile Evidence、DEMO 与报告闭环均已提交。
- `PlatformCatalog → PlatformBinding → PlatformWorker → Runner` 分层与 PostgreSQL 容量租约已实现。
- `HostAgent` 命名已落地；wheel 安装器、systemd `enable + Restart=always`、安全升级、Docker
  前置检查已实现。真实实例 `x5-j6-host` 已安装且 systemd 为 active/enabled；配置为
  `/etc/solution-advisor/host_agent/config.yaml`，控制面 `http://127.0.0.1:8080`。
- `HostImage` 与 `PlatformCandidate` 已分离：HostAgent 注册只记录只读镜像；管理员 API
  `POST /api/admin/host-images/{id}/platform-candidates` 才创建 Candidate。
- `0009_host_images` 迁移、`GET /api/admin/host-images`、候选 Package 骨架生成、Catalog digest
  与 HostImage digest 一致性 Binding 校验已实现。
- 最近完整回归：`36 passed`、覆盖率 `85.02%`；前端 build 通过。

## 未完成

1. AdminPage 平台区域仍是压缩单行模板，尚未实际渲染 HostImage 三态卡片/分组和创建 Candidate 按钮。
2. Candidate Package 当前由控制面进程写入 `platform_packages/candidates`；需改为可审查、持久化的
   接入套件产物，不能依赖容器临时文件系统。
3. 未实现受控接入测试 Runner、测试 Evidence、审核缺项 UI、发布引导。
4. 未实现 HostAgent/镜像视图的独立页面、图标颜色、空/加载/失败状态与浏览器验收。
5. `HostAgent` 当前扫描结果已注册；部署新代码后需复验纯镜像、Candidate、Catalog 三态。

## 设计原则

- Catalog 是全局平台资产，绝不属于某台服务器；A 适配后 B 以相同 digest 复用。
- `platform_id` 只由审核发布 Catalog 产生；镜像名/tag/Agent 输入不能产生平台身份。
- HostAgent 只读发现、注册、心跳、领取获批任务；不自动纳管、不直连 PG/Redis/MinIO。
- 正式 Worker 只在 `AVAILABLE Catalog + HEALTHY Binding` 后创建；Candidate 阶段只能使用受控接入测试 Runner。
- 所有路径、命令、镜像、凭据均受控；不接任意 Shell 或 Docker 参数。

## 实施步骤与验收

1. 格式化/重写 AdminPage 平台区，保留现有配置草稿、Worker 租约和 REAL 卡片。
2. 调用 host-images API，按 `DISCOVERED / INTEGRATING / MANAGED` 三组展示：灰蓝 ○、琥珀 ◐、绿色 ●。
3. 纯镜像弹窗输入受限 `package_id`，调用创建 Candidate；显示 Package、镜像 digest、下一步测试。
4. 将 Package 生成改为版本化 Artifact 或 Agent 侧受控工作目录；实现固定接入测试与 Evidence。
5. 审核通过发布 Catalog；验证 B Host 相同 digest 可 Binding，非同 digest 返回稳定错误。
6. 执行 `uv run pytest -q`、`npm --prefix frontend run build`、`git diff --check`、Compose config/up；浏览器验证。

## 参考资料

- `docs/design/平台治理工作台设计.md`
- `docs/operations/platform-integration-kit.md`
- `docs/operations/HostAgent安装与升级.md`
- `docs/records/M4-C-R1-平台目录纳管与动态Worker分层验收记录.md`
- `docs/operations/x5-a-worker-template.yaml`

## Git

最近提交：`88721f6 feat(platform): 生成候选平台包骨架`。
当前存在未提交的 `docs/design/平台治理工作台设计.md`，以及可能的 AdminPage 开始改动；接手前必须先执行 `git status --short`。
