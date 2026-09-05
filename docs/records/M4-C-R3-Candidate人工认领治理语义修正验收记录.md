# M4-C-R3：Candidate 人工认领治理语义修正验收记录

## 变更结论

Candidate 已从 300 秒租约改为无期限人工认领。`claimed_by`、`claimed_at` 和 `revision` 是当前协作权威；历史
`lease_expires_at` 列仅为旧审计兼容保留，迁移会清空其值，运行时不读取、不倒计时、不自动释放或清理。

```text
UNCLAIMED --管理员原子 Claim--> CLAIMED
CLAIMED --认领人 Release/清理--> UNCLAIMED
CLAIMED --超级管理员 Force Release/清理--> UNCLAIMED
CLAIMED --超级管理员清理后 Force Assign--> CLAIMED(指定 ACTIVE 管理员)
```

## 自动化验收

- 两个管理员竞争认领时，数据库条件更新保证最多一人成功；非认领人编辑、测试和释放均被后端拒绝。
- 人为写入已过期的历史 `lease_expires_at` 后，Workbench 仍显示原管理员认领；旧 `/renew` 接口不存在。
- 手动 Release、超级管理员 Force Release 均删除 Candidate 专属 Package、草稿、验证任务、Evidence 与无引用临时 Artifact，并保留 History、PlatformAudit 和清理摘要。
- Force Assign 先清理原资料，再在同一事务中指定 ACTIVE 管理员并生成干净工作包；普通用户、停用人员和超级管理员不能成为指定目标。
- revision 冲突、三态 Workbench、归档、人员管理、X5/S100 Flow、报告与 PDF 继续由全量回归覆盖。

## 真实浏览器四会话验收

生产近似 Compose 已运行新 API 与迁移 `0027_candidate_manual_claims`。以 SA、U1、U2、U3 四个独立 Chromium
Cookie Session 完成以下真实验收；每个临时账号使用运行时随机初始密码、首次改密后激活，认证材料未写入本记录：

1. U1 创建并 Claim 临时 Candidate；U2 的 Workbench 显示 U1 为处理者，携带最新 revision 的测试写请求返回 `423`。
2. 保持 U1 认领超过旧 300 秒阈值后，Candidate 仍为 `CLAIMED / U1`，未发生自动清理或自动释放。
3. U1 手动 Release 后 Package 为空；U2 再次 Claim 得到没有命令模板的干净工作区。
4. SA 对 U2 Force Release，资料清理完成；随后 Force Assign 给 U1，先清理再生成 U1 的干净工作区。
5. U3 请求人员管理和平台治理 API 都被拒绝为 `403`。SA 停用 U1/U2/U3 后，U1 的旧浏览器会话立即失效并返回 `401`；该状态是未认证会话的正确结果。
6. 验收结束后，SA 再次 Force Release 并归档临时 Candidate；临时账号均为 `SUSPENDED`。History 与 PlatformAudit 保留，接入工作资料未保留。

## 运行与回归清单

```text
uv run pytest -q
npm --prefix frontend run build
git diff --check
docker compose config
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml up --build -d
```

执行结果：全量 pytest、前端构建、diff 检查、两套 Compose 配置和生产近似 Compose 重建均通过。旧 R2-R1 的租约
浏览器结果未被作为本轮验收依据。
