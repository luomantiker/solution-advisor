# M4-C-R2 三角色多管理员协作治理验收记录

## 结论

系统仅持久化普通用户（`USER`）、管理员（`ADMIN`）和超级管理员（`SUPER_ADMIN`）。JWT 仅证明身份，
后端从 `users` 表读取角色；生产未配置可信身份参数时 fail-closed，测试身份必须显式启用。

- 普通用户不能访问平台工作台；模型资产、评估任务、报告和 Artifact 引用按 `owner_subject` 隔离。
- `SUPER_ADMIN` 由数据库局部唯一索引保证唯一性，并通过带原因的受控交接转移。
- Candidate 使用 300 秒 claim 租约、`If-Match` revision 和 `candidate_history`。非持有人只读；当前
  持有人可续租或主动释放。超级管理员只能带原因强制释放，不能接管或转交进行中的接入材料。
- 租约超时、持有人释放、超级管理员强制释放均在同一受控流程中清理该次 Candidate 的 Package、草稿、
  离线检查、验证任务以及仅由 Candidate 引用的 Evidence/Artifact；审计只保留动作、原因、时间、revision
  与清理摘要。下一位管理员重新领取时只能取得全新的工作包。
- R2-R1 将 Candidate 物理删除改为归档：归档释放 claim，并保留 Candidate、History、Artifact、Evidence
  和 PlatformAudit；默认 Workbench 隐藏归档项，超级管理员带原因恢复。活动 `(agent_id, image_digest)`
  由局部唯一索引保证唯一，归档记录不阻止新建活动 Candidate。
- 后端 `platform-workbench` 为 `(agent_id, image_digest)` 提供唯一 `DISCOVERED / INTEGRATING / MANAGED`
  状态；前端只消费该 ViewModel，保留 5 秒后台局部轮询。
- 固定离线 Candidate Runner 仅产出可审查 Package/Evidence，不接收 Shell、Docker 参数、路径、凭据、真实
  板卡或编译扩展。Catalog 以 immutable digest 跨 Host 复用，Binding 必须由目标 Host 重新发现同 digest。

## 验收命令

```bash
uv run pytest -q
npm --prefix frontend run build
git diff --check
docker compose config
docker compose -f docker-compose.prod.yml config
```

自动化隔离会话验收已通过：U1 领取后 U2 只读，续租、revision 冲突、租约超时、主动释放与超级管理员
强制释放均验证资料清理；普通用户被拒绝工作台且不能读取他人资源。旧的“接管”和“重新打开工作区”接口
均固定返回 `410`，不可能把进行中的资料交给另一位管理员。

生产近似 Compose 浏览器验收已通过：使用本地超级管理员可信会话登录、进入“管理 → 平台目录与纳管”，
确认 Workbench 正常加载及 5 秒后台同步说明可见（截图仅保留在受控临时目录，不提交）。当前部署没有可供
验收后自动删除的两名独立受信管理员账号，因此没有在生产数据中创建测试账号；双管理员的独立会话行为由
`test_platform_governance.py` 的隔离 API 会话覆盖。若交付前已有 U1/U2 企业 SSO 账号，应按本文档的浏览器
步骤补做一次人工双会话见证，不需要也不得改写任何 Candidate 历史。

本轮回归结果：`uv run pytest -q` 为 **94 passed**，总覆盖率 **81.34%**（门槛 80%）；前端构建、
`git diff --check`、开发/生产 Compose 配置解析，以及生产近似 `up --build -d` 和 `/api/healthz` 均通过。
