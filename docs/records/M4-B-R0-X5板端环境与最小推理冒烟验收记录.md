# M4-B-R0 X5 板端环境与最小推理冒烟验收记录

## 目标与范围

在既有 `x5-a` 单平台 Agent 及 M4-A 编译闭环上，验证受控 `model.bin` 的板端预检、下发
和固定 Runtime 调用，并将日志、结果和哈希作为 MinIO Evidence 保存。本轮不实现候选镜像
扫描、PlatformCatalog、PlatformBinding、单 Agent 多平台或动态 Worker 分层。

后续收口中，固定 Runtime 命令产生的 profile 原始文件由版本化解析器生成性能 ViewModel；
它只表达本次板端固定调用的测量事实，不作精度、稳定性、功耗或部署推荐结论。

## 实际运行环境与受控连接

- Worker：`x5-a`，运行在控制面所在开发机的通用 Agent wheel。
- 板端连接：Agent Host 本地 `0600` 配置、密码文件和 known_hosts；地址、账户、密码与
  Host Key 未进入 Git、数据库、UI、报告、普通日志或本记录。
- 控制面通信：Agent 仅经 Worker Token 调用 `8080` 反向代理的内部 HTTP API；不连接
  PostgreSQL、Redis 或 MinIO 管理接口。
- 固定板端调用：`hrt_model_exec perf --model_file <受控路径>/model.bin --profile_path <受控路径>/profile`。
- 板端 Runtime：`1.24.5`；原始加载日志显示模型构建版本 `1.24.3`。

## 最终真实验收结果

- M4-A 来源任务：`task_44a72342a2834f06b7e80ffb2f27f716`，状态 `SUCCEEDED`。
- M4-A 编译制品：`compiled_model_artifact / x5_bin / model.bin`。
- `model.bin` SHA256：`f802323de9cbed2c877179598f8b658efaf85ae3c8b33ef9c346bf6349d06b6e`。
- M4-B-R0 最终任务：`task_e561deb2ac2947c49fdfd215be93f522`，状态 `SUCCEEDED`。
- 预检：`SUCCEEDED`；制品下发：`SUCCEEDED`；固定 Runtime 调用：`SUCCEEDED`。
- 板端/系统：`Linux 6.1.83 aarch64 GNU/Linux`；Runtime：`1.24.5`；BPU 设备节点读取
  权限：`ACCESSIBLE`。
- 加载状态：`NOT_SEPARABLE_BY_RUNTIME_COMMAND`。`hrt_model_exec perf` 将加载与调用合并，
  因此没有伪造独立加载成功阶段。
- 输入 SHA256：`NOT_COLLECTED_RUNTIME_INTERNAL_INPUT`；输出 SHA256：
  `NOT_COLLECTED_RUNTIME_PROFILE_ONLY`。原因是本次受控 Runtime 调用没有外部输入文件或
  dump 输出对象；不得据此做精度结论。

## Evidence

| 类型 | URI | SHA256 |
|---|---|---|
| `x5_board_result` | `s3://solution-advisor/artifacts/sha256/c8/c8d63ac59fa55379a375f6705dc4051016787a87d1ecbfe6ce43b84cd7dbed40` | `c8d63ac59fa55379a375f6705dc4051016787a87d1ecbfe6ce43b84cd7dbed40` |
| `x5_board_preflight` | `s3://solution-advisor/artifacts/sha256/be/be348a300425ce6cf7e8bf0bbc5dd5831e27e366598df943a56fcd5c5fce898b` | `be348a300425ce6cf7e8bf0bbc5dd5831e27e366598df943a56fcd5c5fce898b` |
| `x5_board_inference_log` | `s3://solution-advisor/artifacts/sha256/1d/1d749166bfd845cbd1860c9a022bd6efdbb283b8b5d76db0a906b530a03796fb` | `1d749166bfd845cbd1860c9a022bd6efdbb283b8b5d76db0a906b530a03796fb` |
| `x5_board_load_log` | `s3://solution-advisor/artifacts/sha256/bd/bdf6bd402c152606795aec40f5517878fb862fb67f49ad8fff8055bb6858461c` | `bdf6bd402c152606795aec40f5517878fb862fb67f49ad8fff8055bb6858461c` |

另有 `BOARD_LOG` profile 原始文件，保存于同一任务 Evidence 中；性能解析会保留原始文件、
解析器版本和解析结果三者关联。

## profile 性能解析收口

在不重新连接或运行板卡的前提下，管理员通过受保护的离线解析入口对最终任务既有的 MinIO
profile Evidence 执行了解析（解析器 `x5-hrt-profile-1.0`）。实际结果如下：

- 环境：`Linux 6.1.83 aarch64 GNU/Linux`；Runtime `1.24.5`；BPU 设备节点
  `ACCESSIBLE`；Runner `hrt_model_exec perf`。
- 运行条件：模型 `model`、`core_id=0`、`thread_num=1`、`frame_count=200`、
  `run_time=66.989 ms`。
- 性能测量：FPS `2985.5647942199466`；平均延迟 `0.3264048397541046 ms`。
- 分段：`BPU_x5_conv_relu_linear_subgraph_0` 的 avg/min/max 为
  `0.249425/0.198/1.071 ms`；`Preprocess` 的 avg/min/max 为
  `0.006825/0.005/0.022 ms`。
- profile 存在 CPU 执行段（`CPU_inference_time_cost`），但这不等于模型 CPU 算子；对应
  M4-A 编译日志 `allocation.CPU=[]`，因此模型 CPU 算子结论为
  `NOT_DETECTED_IN_COMPILE_ALLOCATION`。

上述数值只描述这一次固定 Runtime profile 的板端测量。精度、稳定性、功耗和推荐部署仍为
`NOT_VERIFIED`；精度和功耗已分别预留“版本化输入/输出比较”和“板端功耗采样器”扩展点。

## 失败尝试与修复

首次固定调用错误使用 `--profile`，板端 Runtime 返回 `unknown command line flag 'profile'`；
该任务如实记录为 `FAILED`，未覆盖历史。根据板端 `--help` 修正为 `--profile_path` 后，最终
任务成功。期间发现 Agent 未上传独立预检文件，已补齐并以最终任务重新执行一次受控调用。

## 自动化、Compose 与浏览器验收

- `uv run pytest -q`：`32 passed`，总覆盖率 `86.49%`。
- `npm --prefix frontend run build`：通过（Vue 类型检查与 Vite 构建）。
- `git diff --check`：通过。
- `docker compose config`、`docker compose -f docker-compose.prod.yml config`：通过。
- `docker compose -f docker-compose.prod.yml up --build -d`：真实启动 PostgreSQL、MinIO、Redis、
  migrate、API、Web 与 common-analyzer；宿主机仅暴露 Web `8080`。
- 浏览器：Playwright 经 `8080` 完成上传 → Profile → DEMO → Mock PDF 下载回归；另实际访问
  `/tasks/task_e561deb2ac2947c49fdfd215be93f522`，板端报告页正常渲染并显示全部
  `NOT_VERIFIED` 边界。
- API/PDF：最终任务报告 API 正常；`pdftotext` 可提取板端预检、制品哈希和全部
  `NOT_VERIFIED` 边界，未包含 FPS 或 Latency。

## 已知限制与后续建议

1. 当前 Runtime 调用不提供受控外部输入或 dump 输出，输入/输出 SHA256 为 `NOT_COLLECTED`；
   后续精度阶段必须引入版本化输入样本、输出 dump 与比较规则。
2. profile 原始文件已保存；当前解析 FPS、平均延迟、运行条件、分段耗时与 CPU 执行段。后续
   可受控启用 `thread_num`、`perf_time` 与 `hrut_bpuprofile -b 0 -r0`，并明确采样时长、
   指标口径和证据保留策略；功耗仍待确定采集命令。
3. 功耗采集命令尚未确定，保持 `NOT_VERIFIED`。
4. 候选镜像、平台目录、平台纳管和动态 Worker 分层留给
   `M4-B-R0-平台目录纳管与动态Worker分层`，不能与本次单平台闭环混合实现。
