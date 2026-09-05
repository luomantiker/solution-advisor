# M4-C-R5-R1 平台工作台与人员权限验收记录

## 视觉与组件体系

- 新增统一 `AppShell`、`PageHeader`、`MetricCard`、`SectionCard`、`StatusBadge`、`SegmentTabs`、`EmptyState`、`SidePanel` 与 `ConfirmDialog`；平台治理和人员管理不再沿用原始“标题 + 原生按钮 + 三列容器”的页面结构。
- 保持第一版预览的深海军蓝侧栏、Realthon 原始 Logo、菜单图标、通知/帮助/收起入口、宽白色内容画布和浅灰蓝背景；未采用第二版风格。
- 平台治理页使用四张真实 ViewModel 指标卡、三态 Candidate 泳道、统一状态标签、空状态、分段页签及 Candidate 详情抽屉。页面只消费后端 `platform-workbench` 返回的数据，不自行拼接状态。
- 人员管理页使用同一页头、指标卡和卡片化表格；新增、启停、重置密码分别使用抽屉或确认对话框。

## 权限纠偏

- ADMIN 可进入人员管理，只能列表、创建、更新、启停和重置 USER。
- ADMIN 对已知 ADMIN / SUPER_ADMIN ID 的直接 PATCH、停用、重置请求均由后端明确返回 `403 / admin_can_manage_users_only`，不依赖前端隐藏。
- USER 访问人员管理页面被路由收敛，直连人员 API 与平台治理 API 均由后端拒绝。
- SUPER_ADMIN 保留管理 ADMIN / USER 的范围；默认密码 `Realthon_1`、直接 `ACTIVE`、无需强制首次改密保持不变。

## 浏览器验收与截图

- 以本地超级管理员 Cookie Session 实测平台治理和人员管理页面均正常加载；截图见：
  - [平台治理工作台](assets/M4-C-R5-R1-platform-workbench.png)
  - [人员管理](assets/M4-C-R5-R1-people-management.png)
  - [普通用户视角](assets/M4-C-R5-R1-user-view.png)
- 通过人员管理页面创建临时 `r5r1u1`、`r5r1u2`（ADMIN）和 `r5r1u3`（USER），均使用默认密码并直接 ACTIVE；U1 页面只显示 USER，直接停用 SUPER_ADMIN API 返回 `403`；U3 页面和 API 均被拒绝。验收结束后三个临时账号均通过人员管理页面停用，旧会话失效。
- 修正“归档历史遮蔽源镜像”的 ViewModel 缺陷后，真实 HostAgent 已发现的镜像正确回到 `DISCOVERED`；归档项仍只在“显示归档”下出现。以隔离 Candidate `candidate_04af366610734285ae9f964b7422da61` 完成两个独立管理员浏览器 Session 见证：U1 Claim 并登记工作资料，U1 Release 后资料被清理；U2 重新 Claim 获得干净工作区，U1 对其写请求被后端拒绝为 `423`；超级管理员 Force Release 后清理，并带原因指定 U1，确认不继承 U2 资料。随后将该临时 Candidate 归档，未触碰历史 MANAGED、归档或 M5 资源。

## 自动化与构建

- 新增 ADMIN 仅管理 USER、已知特权账号 ID 直接 `403`、USER 人员 API `403` 的自动化覆盖。
- 新增归档后源镜像恢复 `DISCOVERED`、归档历史仅在显式开关展示的自动化断言；保留并回归 Candidate Claim、非认领人 `423`、Release 清理、Force Release / Assign、revision 冲突相关测试。
- 完整 `uv run pytest -q` 已通过；覆盖率报告总计为 `81%`，高于项目 `80%` 门槛。前端构建、`git diff --check`、开发/生产 Compose 配置检查与生产近似 Compose 重建均通过。
