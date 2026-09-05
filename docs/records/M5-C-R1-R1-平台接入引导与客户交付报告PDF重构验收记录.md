# M5-C-R1-R1 平台接入引导与客户交付报告 PDF 重构验收记录

## 交付范围

- 平台管理工作台为发现镜像、人工接入中、已发布平台分别提供当前上下文、输入约束、系统动作和资料/Evidence 去向说明。
- `EvaluationFlow` 在创建时冻结通用 ONNX/Profile 分析快照；客户报告不读取 Candidate、管理员验证、其他 Flow 或 DEMO 数据。
- 新增追加式 `ReportRevision`：首次预览生成 V1，显式请求才生成新版本；PDF 作为 Artifact 绑定到对应版本，历史版本不会被静默覆盖。
- 客户网页/PDF 固定为四章：结论摘要、ONNX 检测、分平台适配与板端结果、优化建议；附录保留 Evidence、制品、规则、Runner、Parser 和版本快照。

## 自动化验收

- `tests/test_current_platform_flow_report.py` 覆盖 X5/S100 Flow 的冻结 Runner、制品格式、解析器、实测指标、报告 V1/V2、PDF 版本绑定和所有者隔离；另覆盖历史 Profile 快照不可用时不猜测事实、失败阶段原因、ONNX 输入/输出与无性能值的报告表达。
- `tests/test_candidate_stage_guidance.py` 回归发现、接入中、已发布三个引导状态，以及人工认领只读和释放即清理资料的说明边界。
- `tests/test_flow_parallel_capacity.py` 回归容量 3 的编译并行、同 Binding 板端串行、多个 Flow 的独立 PDF 生成。
- PDF 自动检查使用 A4 渲染、页数、嵌入式 CJK 字体和 ASCII Flow/模型/平台事实提取。中文与 ASCII 分别由嵌入的 CJK/Latin 字体承载，避免模型名、Flow、SHA256、版本等字段在客户 PDF 中空白。

## 真实浏览器与 PDF 渲染验收

1. 使用本地超级管理员的独立浏览器会话打开真实终态 S100 Flow `flow_72be3b8b64c148a7ae41213272c2124c`：网页报告展示该 Flow 的冻结 Profile、11 项当前 Flow Evidence、S100 固定 Runner `s100-runner-1.0.0`、解析器 `s100-hrt-profile-1.0` 和固定条件下实测性能；未出现 Candidate、管理员验证、其他 Flow 或 DEMO 事实。
2. 浏览器中先保留 V1，再显式生成至 V6；每个版本独立可下载，旧版本没有被覆盖。最终验收下载文件为 `flow_72be3b8b64c148a7ae41213272c2124c-报告-V6.pdf`。
3. 将 V6 用本机 PDF 渲染器按 144 DPI 渲染：3 页 A4，中文、Logo、模型名、Flow、版本 V6、时间、S100、页眉页脚页码和章节表格均可见，无方框、乱码、裁切或重叠。封面独立成页，正文四章连续排版；页眉页脚与正文的中英文混排由嵌入的 CJK/Latin 双字体承载。
4. 在管理员浏览器会话打开平台管理：已发布区域显示“接入引导：已发布平台”，明确 Catalog/Binding/READY Worker 的含义、调度条件和资料/Evidence 的去向；未变更任何现有 Candidate、Catalog、Binding、Worker 或 M5 Evidence。
5. 删除整次 Flow 的回归由自动化覆盖：仅终态 Flow 可删，并会清理该 Flow 专属内部阶段、Evidence/Artifact、ReportRevision/PDF；模型、Catalog 和其他 Flow 不受影响。

## 已知边界

- 历史 Flow 在创建时未冻结 Profile 快照时，仅允许从可证明关联的 Profile/模型生成带 `HISTORICAL_PROFILE_BACKFILL_VERIFIED` 标识的新版本；证据不足则显示快照不可用，不重新分析或伪造历史结论。
- 输出一致性、精度、稳定性、功耗和部署推荐继续需要各自独立 Evidence；报告不会据编译或板端性能自动推断这些结论。
