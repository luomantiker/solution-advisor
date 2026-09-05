# M4-C-R2-R1 本地账号人员管理与双管理员真实验收记录

> 历史说明：本记录中的续租与 300 秒自然超时描述是当时 R2-R1 的验收事实；自 M4-C-R3 起已由无期限人工认领、手动释放和“清理后指定管理员”取代，不再是当前运行语义。

## 环境与身份

- 基线：`dc2bd20 feat(平台): 接入三角色与多管理员协作治理`。
- 环境：生产近似 Compose；测试身份关闭，本地认证为服务端 Cookie Session。
- 超级管理员以既有本地身份登录；验收中通过人员管理页面创建 U1、U2（管理员）和 U3（普通用户）。
  初始密码仅在隔离浏览器进程内随机生成和输入，未写入页面、日志、审计、Evidence 或本文档。

## 真实浏览器验收

1. 四个相互隔离的浏览器 Cookie Session 分别登录 SA、U1、U2、U3；U1/U2/U3 均完成首次改密后变为
   `ACTIVE`。
2. U3 访问人员管理和平台治理 API 均返回 `403`；其会话不具有管理员权限。
3. 使用一个验收专用、未关联 Catalog/Binding/Worker/Flow 的 Candidate：U1 claim 成功，U2 claim 与写入均返回
   `423 candidate_claimed_by_other`；U1 续租后主动释放，U2 重新 claim 的工作包为干净状态。
4. SA 对 U2 当前 claim 执行带原因强制释放，未发生接管或材料转交；随后归档验收 Candidate。
5. SA 停用 U1/U2/U3；三个浏览器中已建立的 Cookie Session 均立即被后端拒绝。人员与 Candidate 审计保留，
   未删除 M5 的 Flow、Artifact、Evidence 或报告。

## 自动化与边界

- 本轮新增本地密码 Provider、IdentityLink、服务端 Session、人员状态/修订/审计和失败登录临时锁定测试；
  密码 Hash、Cookie、Token 和初始密码均不出现在 API 响应或审计摘要。
- 300 秒自然超时的清理路径由既有 `test_candidate_expiry_and_release_clear_material_then_next_admin_starts_clean`
  自动化覆盖。本次真实浏览器验收覆盖 claim、续租、主动释放、强制释放及清理；未为等待 300 秒而保留或
  修改任何临时账号和 Candidate。
