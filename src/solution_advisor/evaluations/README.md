# 评估流程模块

本目录实现用户可见的受控评估流程，以及平台内部的编译和板端性能阶段。

## 领域模型

```text
EvaluationFlow（一次用户评估）
├─ X5_COMPILE → REAL_BOARD_SMOKE
└─ S100_COMPILE → S100_BOARD_PERF
```

`EvaluationFlow` 是用户查看、分享、下载报告和删除评估的唯一入口。内部阶段独立
持久化、独立租约、独立状态及 Artifact/Evidence，供管理员下钻诊断；它们不会在模型
列表中被展示成多份用户评估。

## 平台隔离

- X5 仅使用 `model.bin / x5_bin`、X5 Evidence 和 `x5-hrt-profile-1.0`。
- S100 仅使用 `.hbm / s100_hbm`、S100 Evidence 和 `s100-hrt-profile-1.0`。
- 自动板端阶段只可引用同一 Flow、同一平台、同一成功编译阶段中已登记 SHA256 的制品。
- 任何跨 Flow、跨平台、跨 Worker 的制品或 Evidence 引用都应由后端拒绝。

## 容量与状态

编译阶段可在 Binding 的多个容量槽位中并行，每个槽位对应一个短时固定 Runner 容器和
一条 PostgreSQL 容量租约。同一 Binding 的板端阶段必须串行，避免同一板卡争用；不同
Binding 可以并行板测。

Flow 汇总保留各平台真实状态：等待、执行中、成功、部分成功、失败、取消、超时和未执行。
一个平台成功不能覆盖另一个平台的失败或等待状态。

用户 API 只接收 `model_profile_id`、已发布 `catalog_id` 列表和受控预设；所有权、分享、
Evidence 下载与删除均由后端权限检查。
