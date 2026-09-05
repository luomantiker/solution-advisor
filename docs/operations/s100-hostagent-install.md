# S100 HostAgent 安装与受控验证

本手册安装的是经过 Git 审核的 `s100-runner-1.0.0`，不是网页脚本编辑器。Candidate 页面只登记规则；实际命令、镜像、受管模型和板端连接均由本机受保护配置固定。用户侧 Flow Agent 只能领取其
快照冻结的 `S100_COMPILE` 与 `S100_BOARD_PERF`，当前发布 Release 为 `S100 / 3.7.0-r1`。

## 目录与权限

在 S100 Host 上使用以下目录：

```text
/opt/solution-advisor/worker-agent/
/opt/solution-advisor/platform-packages/s100/
/etc/solution-advisor/workers/s100-<实例>/config.yaml
/etc/solution-advisor/secrets/s100-<实例>/
/var/lib/solution-advisor/worker/s100-<实例>/work/
/var/log/solution-advisor/worker/s100-<实例>/
```

`config.yaml`、Worker Token、板端口令/私钥和 known_hosts 均应由专用服务账号持有，目录权限为 0700、秘密文件为 0600。它们不得提交 Git、写入数据库、浏览器、报告或普通日志。

## 配置与启动

以 `s100-worker-template.yaml` 为结构参考，在 Host 私有配置中填写控制面地址、实例 ID、Token 文件、已审核镜像、Package 安装路径、16×16 fixture、受保护板端 profile 和工作目录。能力固定为 `static_check`、`compile`、`board_smoke`；用户 Flow 常驻入口固定为：

```text
python -m solution_advisor.workers.s100_evaluation_agent --config /etc/.../flow.yaml
```

Candidate 的一次性系统验证仍使用 `s100_validation_agent --once`；它不能替代用户 Flow 的 Evidence。
常驻服务由 systemd 运行上述 Flow 入口。Agent 注册、心跳、领取、Artifact/Evidence 上传及完成回传只使用
Worker Token 调控制面；不直连 PostgreSQL、Redis 或 MinIO。

## 验收与故障处理

管理员先认领 Candidate、保存当前修订并通过离线契约检查，再发起真实验证。只有 Agent 对该修订实际产生 `.hbm / s100_hbm`、编译日志、板端预检、调用日志、profile 及结果，并经控制面入库后，才可生成审核 Catalog。失败时 Candidate 保持不可发布，保留已上传 Evidence 和稳定的 `reason_code`；修订变化会使旧结果失效。

不得把 M5-A-R1 的人工终端日志或人工 `.hbm` 当作本步骤成功输入。
