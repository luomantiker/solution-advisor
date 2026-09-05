# M4-A-R1 X5 Worker、REAL 编译与 Evidence 验收记录

## 完成能力

- X5 Platform Package 含 manifest、镜像锁、Python Runner、规则、报告说明和离线测试。
- 通用 Agent 使用 Worker Token 调用控制面完成注册、心跳、claim、模型下载、Evidence 上传与完成回传；不直连 PostgreSQL、Redis、MinIO。
- PostgreSQL 租约驱动 `QUEUED → CLAIMED → RUNNING → SUCCEEDED/FAILED/CANCELLED/TIMEOUT`；终态完成幂等，迟到失败不覆盖成功。
- X5 产物口径统一为 `compiled_model_artifact / x5_bin / model.bin`；不是 HBM。
- Evidence 含静态检查、完整编译日志、编译摘要、Runner 结果和编译制品，数据库仅存元数据。

## Compose 实际验收

生产近似 Compose 的 PostgreSQL、MinIO、Redis、migrate、API、Web、common-analyzer 已启动。
通过 Web `8080` 上传 `tests/fixtures/minimal.onnx`、异步生成 Profile、管理员创建 REAL 任务，外部 Host 运行通用 Agent 执行锁定镜像
`openexplorer/ai_toolchain_ubuntu_20_x5_gpu:v1.2.8-py310` 中的 `hb_mapper 1.24.3`。

最终任务 `task_44a72342a2834f06b7e80ffb2f27f716` 为 `SUCCEEDED`：

| 对象 | SHA256 | 大小 |
|---|---|---:|
| `model.bin` | `f802323de9cbed2c877179598f8b658efaf85ae3c8b33ef9c346bf6349d06b6e` | 264055 B |
| 完整编译日志 | `5959ca070bd8c509a03b77523e427c5a0ee179d579a2505de531b4d759dab297` | 20841 B |
| 静态检查 | `330a11daa4816ca46ad61fc5b69fee9d2b29746f6830c1db57f52b6e2a1ef71d` | 489 B |
| 编译摘要 | `3b95783f12dafbed0732ed70af31e7c3135ddaaf5e2ced55f19fa207a8856fdb` | 148 B |

日志解析 BPU：`HZ_PREPROCESS_FOR_input`、`Conv_0`、`Gemm_3`；CPU 列表为空。
PDF 下载后使用 `pdftotext` 验证可读。自动化测试 `26 passed`，覆盖率 `86.82%`；
`npm --prefix frontend run build` 通过。

## 边界与下一阶段

`board_validation=NOT_EXECUTED`；性能、精度、稳定性和交付性部署结论均为
`NOT_VERIFIED`。本记录不构成板端或性能证据。M4-B 前置条件是板卡 Secret、受控
连接/取消恢复、原始性能与精度 Evidence、对应权限和数据保留策略。
