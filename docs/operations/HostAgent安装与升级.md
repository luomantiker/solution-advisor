# HostAgent 安装、常驻与安全升级

HostAgent 以通用 Python wheel 发布；wheel 只是程序包，安装器负责把它变成常驻服务。统一运行配置为：

```text
/etc/solution-advisor/host_agent/config.yaml
/etc/solution-advisor/host_agent/registration-token
/etc/systemd/system/solution-advisor-host-agent.service
```

首次安装和升级使用同一个受控命令。未传 `--control-plane-url` 时，安装器会提示：

```text
控制面地址 [http://127.0.0.1:8080]：
```

直接回车采用默认值；也可输入部署环境的控制面地址。Token 只应位于本机受保护文件，不能写入命令行、
Git 或日志。

```bash
sudo solution-advisor-host-agent-install \
  --wheel solution_advisor-<version>-py3-none-any.whl \
  --token-file /path/to/worker-registration-token \
  --instance-id x5-j6-host
```

安装器会创建独立 venv、安装/升级 wheel、保留既有运行配置中未被本次设置覆盖的项、更新 systemd 单元，
并执行 `daemon-reload`、`enable`、`restart`、`is-active`。因此首次安装完成后 HostAgent 已运行，后续
服务器重启也会自动启动；重复执行同一命令是升级模式，既有服务的开机自启与重启策略保持不变。

安装器先检查 `docker --version`。Docker 已存在时不修改宿主环境；缺失时会明确询问是否授权安装
`docker.io` 并启用 Docker 服务。用户未输入 `y/yes` 时安装器会停止，不会擅自安装任何系统包。

验证：

```bash
systemctl is-active solution-advisor-host-agent.service
systemctl is-enabled solution-advisor-host-agent.service
journalctl -u solution-advisor-host-agent.service -n 50 --no-pager
```

HostAgent 只使用 Worker Token 调用控制面内部 HTTP API；不会直连 PostgreSQL、Redis 或 MinIO。安装、
升级和重启本身不会创建 REAL 任务、执行编译或访问板卡。

## 并行执行容量与验收

`config.yaml` 的 `max_concurrency` 是该 HostAgent 可同时持有的**编译执行槽位上限**。Agent 启动时将此
上限登记到控制面；管理员只能把同一 Host 的 `PlatformBinding.max_concurrency` 设置为不大于该登记值的
数值。它不是网页上的任意数字，也不是容器数的事后统计。

```yaml
# 仅在完成该 Host 的真实容量验收后才提高；取值 1..32。
max_concurrency: 3
```

一个槽位对应一个短时、固定 Runner 容器和一条 PostgreSQL 容量租约。每个槽位独立续租；取消、失败、
超时或租约失效都会释放对应槽位。控制面只在所有槽位占满时显示 `BUSY`，尚有空闲槽位时仍显示 `READY`。

`REAL_BOARD_SMOKE`（X5）和 `S100_BOARD_PERF`（S100）不随编译容量并行：同一
`PlatformBinding` 代表一个具体板端执行位置，同一 Binding 同时至多一个板端性能任务，防止多个
`hrt_model_exec perf` 竞争同一块板卡。编译成功后产生的板端阶段会继续自动串联，但在板端互斥条件满足
之前保持排队。

### 两阶段、跨 Flow 的实际调度约定

一次用户可见的 `EvaluationFlow` 对每个选择的平台冻结 Catalog、Binding、Worker、Runner Release、镜像锁、
规则、制品格式、Evidence 家族和解析器版本，然后创建两个内部阶段：

```text
平台编译阶段（X5_COMPILE / S100_COMPILE）
→ 已登记且校验 SHA256 的平台制品
→ 自动板端阶段（REAL_BOARD_SMOKE / S100_BOARD_PERF）
```

- **编译可并行：** 同一 Binding 的多个编译任务可分别占用 `max_concurrency` 内的不同槽位；每个槽位启动一个短时、固定 Runner 容器，任务结束即销毁并释放租约。
- **板测按板卡串行：** 编译容量不等于板卡容量。同一 Binding 的板端阶段互斥；多个 Binding（例如 X5 与 S100 各自的已授权板卡）可以并行板测。
- **多个 Flow 相互独立：** 每个 Flow 保留自己的阶段、租约、Artifact、Evidence 和快照。一个 Flow 或一个平台失败、取消、超时，不覆盖其他 Flow 或同一 Flow 其他平台的真实状态。
- **不可静默改投：** 已冻结的 Worker 离线、DRAINING、失去能力或容量不可用时，该阶段保持等待，或按超时/失败规则终态并记录中文原因；不得转交给其他 Worker。
- **汇总不等于单阶段成功：** 只有所选平台的最后阶段均成功，Flow 才是成功；一边成功、一边失败是部分成功；编译成功而板端仍等待/运行时，Flow 仍未完成。

容量验收必须同时覆盖：多个编译任务使用不同 `slot_index` 的并行记录、同一 Binding 板端任务的先后执行、不同 Binding 板端任务可重叠，以及每个 Flow 的 Evidence 与最终汇总均独立正确。

提高容量的受控验收步骤为：先升级 Agent wheel 并在 Host 配置中登记目标上限；确认 Agent 心跳和
Binding 健康；由管理员在 Binding 页面把容量提高到不大于登记值；创建与目标槽位数相同的真实编译任务；
验证每项任务有不同 `slot_index`、固定 Runner 容器并发运行、全部生成独立 Evidence 并释放租约。若任一
项失败，容量不得据此提高，保留失败任务、日志和 Evidence 后将 Binding 降回已验收值。

## X5 固定 Runner 的共享工作目录

若该 HostAgent 已通过 `PlatformBinding` 承载 X5 REAL 编译，实例配置还必须由 Host 管理员补充一个
专属 `work_root`，例如：

```yaml
work_root: /var/lib/solution-advisor/host_agent/work
```

目录应归运行 Agent 的账户所有，且不向普通用户开放。systemd 服务启用 `PrivateTmp=true` 时，Docker
守护进程看不到 Agent 私有 `/tmp`；固定 Runner 的输入、输出必须在此 Host 管理的共享工作目录中创建，
再由程序以固定只读/读写挂载交给 Runner。此字段不是页面、任务或模型可传入的路径，不能借此接受任意
宿主机目录。
