# M5-B-R1 用户评估工作台与报告体验验收记录

## 范围

本轮将已存在的 X5、S100 及联合 `EvaluationFlow` 的真实执行事实交付到普通用户界面。未修改
调度、Worker、Runner、Artifact、Evidence、解析器或报告事实语义；平台治理和 Candidate 流程
不在本轮范围内。

## 已实现

- 第一版 Realthon AppShell 下提供评估工作台、上传模型、我的模型和我的报告导航；管理员入口仍
  按角色显示。
- 工作台只返回当前用户 Flow 摘要、可访问模型数量和终态报告入口，不返回 Host、Worker、Binding、
  Agent、镜像锁或 Runner 实例。
- 模型详情使用三步创建向导：选择模型、按平台类型选择可调度版本、确认受控预设；用户 API 仍只
  接受 `model_profile_id`、已发布 `catalog_id` 和受控预设。
- Flow 详情展示本次 Flow 的阶段时间线、平台最终结果、同 Flow Evidence 下载和脱敏冻结快照；运行中
  每 5 秒局部刷新。冻结快照不展示执行 Host、Worker、Binding、Agent 或镜像锁。
- 报告中心和 PDF 只汇总当前 Flow 的真实最终阶段、制品格式、固定 Runner、解析器及有 Evidence
  支持的固定条件数据；没有把 Candidate、管理员验证、其他 Flow 或 DEMO 事实混入结论。

## 权限与资源隔离

- `GET /evaluation-workbench` 只返回当前用户拥有的 Flow 和模型访问范围。
- Flow、报告、Evidence 列表与 Evidence 下载均由后端再次校验 Flow 所有者或管理员权限；其他普通
  用户访问同一 Flow 返回 404。
- 模型内容全局去重不改变逻辑归属；被分享模型仅在明确 ModelAssetAccess 授权下出现在接收者范围。

## 自动化验证

- 定向覆盖：普通用户工作台只列出本人 Flow，当前 Flow Evidence 可读，其他普通用户不能读取 Flow 或
  Evidence；X5/S100 Flow 报告与 PDF 兼容回归。
- 定向 `tests/test_current_platform_flow_report.py`：2 项通过。
- 全量 `uv run pytest -q`、前端 `npm --prefix frontend run build`、`git diff --check`、默认及生产
  Compose config 均在本轮收口时通过；生产近似 Compose 已重建，API、common-analyzer、Web、迁移
  依赖容器均恢复运行。

## 浏览器验收

1. 通过人员管理页面新建独立普通用户 `m5br1accept`，浏览器登录后验证工作台、即时文件名显示、
   上传、ONNX 分析和模型详情；由三步向导创建联合 Flow
   `flow_d7ebe31b31bf46c19af283132c16d00c`。
2. 该 Flow 的 X5 编译、S100 编译、X5 板端性能、S100 板端性能均真实成功，Flow 汇总为“成功”。
   浏览器 Flow 详情和 PDF 下载完成；PDF 可提取中文文本，显示 X5 `x5_bin / x5-hrt-profile-1.0`
   以及 S100 `s100_hbm / s100-hrt-profile-1.0` 的各自阶段事实，未作无条件性能排名。
   同一独立 Session 的“我的报告”页面只列出该用户自己的联合 Flow，并可进入其详情。
3. 通过不同浏览器 Session 新建 `m5br1other`，访问上述 Flow 的后端 API 返回 404；因此不能读取
   他人 Flow 或 Evidence。
4. Playwright 截图保存在验收主机受控临时目录：`/tmp/m5-b-r1-workbench.png`、
   `/tmp/m5-b-r1-model-detail.png`、`/tmp/m5-b-r1-wizard-platforms.png`、
   `/tmp/m5-b-r1-complete-flow.png`、`/tmp/m5-b-r1-isolation.png`；下载 PDF 为
   `/tmp/m5-b-r1-flow-report.pdf`。截图和下载件不含认证材料。
5. 两个临时浏览器验收账号已在人员管理页停用；本轮 Flow、Artifact、Evidence 和审计事实保留，
   不以停用账号替代或改写历史结果。
