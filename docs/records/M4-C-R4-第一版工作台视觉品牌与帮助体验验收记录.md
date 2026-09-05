# M4-C-R4 第一版工作台视觉、品牌与帮助体验验收记录

## 范围

本轮在 M4-C-R3 的无期限人工认领语义之上，固化第一版工作台视觉基准。未修改 M5 Flow、Artifact、Evidence、报告/PDF、三角色持久化模型或 Candidate 后端状态机。

## 认证前置

`678b17d fix(认证): 调整本地账号默认密码与会话体验` 已在本轮开始前完成全量回归并普通推送。产品策略保持不变：人员创建/密码重置默认 `Realthon_1`、账号直接 `ACTIVE`、不强制首次改密；用户主动改密后需重新登录。

## 实现结果

- 复制受控的 Realthon 原始 PNG Logo 到 `frontend/src/assets/`；展开侧栏显示 Logo 与品牌名，收起后保留可访问 Logo 图标和 tooltip。
- 第一版工作台采用深海军蓝左侧导航、宽白色内容画布和既有路由/页面信息架构；未更换为第二版色板或重排业务页面。
- 导航按后端会话角色收敛：普通用户仅有上传和模型入口；管理员增加平台治理；超级管理员增加人员管理。前端路由保护只作体验收敛，后端 `403` 仍是最终授权边界。
- 左下通知在用户主动打开时读取现有账号审计、本人评估流程状态和管理员可见的平台审计；服务端只返回固定、脱敏标签及时间，不返回审计原文、Token、板端地址、私有路径或 Artifact URI。未增加 WebSocket、SSE 或全局轮询；无事件时显示空状态。
- 左下帮助按当前页面和角色呈现受控版本化内容，覆盖用户评估资源边界、管理员 Candidate Claim/Release/阻塞、超级管理员人员/强制释放/清理后指定、Candidate 当前动作影响及人员管理默认密码/会话影响。

## Candidate 语义回归

帮助、通知标签和 Workbench 均保持 R3 人工认领：`UNCLAIMED` 可 Claim；`CLAIMED` 仅认领人写入；手动 Release 清理本次资料；超级管理员可带原因 Force Release 或清理后指定 ACTIVE 管理员。不存在租约、续租、倒计时、自然超时或自动释放；`revision / If-Match` 冲突保护继续有效。

## 自动化与浏览器验收

自动化覆盖 Logo 资产、侧栏收起、帮助角色内容、空通知、默认密码/直接 ACTIVE/改密会话失效，以及 R3 Candidate 人工认领路径。完整 `uv run pytest -q` 已通过：`98 passed`，总覆盖率 `80.52%`，达到项目 `80%` 门槛；前端 `npm --prefix frontend run build`、`git diff --check`、开发/生产 Compose 配置检查也已通过。生产近似 Compose 已重建，Web、API、common-analyzer、PostgreSQL、Redis、MinIO 均正常，健康接口返回 `ok`，迁移版本为 `0028_local_default_password`。

已用 Playwright 隔离 Cookie Session 实测：超级管理员通过人员管理页面创建一名管理员和一名普通用户（默认密码 `Realthon_1`、直接 `ACTIVE`）；三种身份分别确认对应菜单、帮助内容和普通用户通知空状态；管理员访问人员管理被前端路由带回首页，普通用户不显示也不能进入平台治理/人员管理。验收结束后两名临时账号均通过页面停用，未影响 M5 资源。

随后发现并修复一处本地会话回归：旧 `AdminPage` 只在浏览器存在 SSO Bearer Token 时加载控制台，导致已通过同源 HttpOnly Cookie 登录的本地超级管理员错误看到“请先登录”。现已统一为页面挂载时主动验证受保护接口：有 SSO Token 才发送 `Authorization`，本地会话通过 `credentials: same-origin` 复用 Cookie。修复后以 Playwright 本地超级管理员独立会话实测，`analyzer-config`、`worker-instances`、`drafts`、`history`、`platform-workbench`、`platform-types`、`platform-catalogs` 七个管理接口均返回 `200`，工作台正常显示“当前配置”。

当前生产近似库没有可安全变更的 `INTEGRATING` Candidate：仅有已接入平台和历史归档 Candidate。为保护历史 Evidence/Artifact，本轮没有恢复或清理归档记录来制造演练对象。Candidate Claim、非认领人 `423`、Release 清理、Force Release/Assign 和 revision 冲突已由完整自动化回归；此前 R3 的四独立浏览器 Candidate 验收记录继续有效。下一次有新发现镜像且创建可回收的 Candidate 时，可补一次 R4 同视觉下的双管理员实机浏览器复核。
