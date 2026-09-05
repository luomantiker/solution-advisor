# 平台 Runner Release 与受控验证设计

## 目的

平台接入页面只保存 Candidate 的声明性资料；它不是 Shell、Docker、SSH 或板端控制台。可执行能力只能来自 Git 审查后的 Platform Package 与固定 Runner Release。

```text
Platform Package（Git）
→ Runner Release（版本、源码哈希、镜像锁、能力）
→ Host 受控安装（密钥与板端资料仅在 Host）
→ Candidate 当前 revision 的真实验证
→ Evidence / Artifact / 审计
→ Catalog 审核发布
```

页面仅能查看 Release、验证状态、失败原因与 Evidence，并触发已安装 Release 的固定验证；不能编辑 Runner 源码、命令、Docker 参数、板端地址、凭据或宿主机路径。

## S100 3.7.0 Release

`platform_packages/s100/` 是 `s100-runner-1.0.0` 的唯一源码。它锁定
`registry.d-robotics.cc/deliver/ai_toolchain_ubuntu_22_s100_s600_cpu:v3.7.0`，固定编译调用为
`hb_compile --fast-perf --march nash-e --model {model}`，但 `{model}` 仅由 HostAgent 的受管输入替换。

真实产物为 `.hbm`，Artifact 格式为 `s100_hbm`；不得写成 X5 的 `model.bin` 或 `x5_bin`。板端固定 Runtime 是经实际确认的 `hrt_model_exec perf`。编译容器 UCP 3.13.6 与当前板端 UCP 3.7.3 不同，二者均必须进入 Evidence。

性能只表示版本化 S100 fixture 的一次板端测量。输出一致性、任务精度、稳定性、功耗和部署推荐均保持 `NOT_VERIFIED`。

## 发布门禁

Catalog 只能引用当前 Candidate revision 的真实编译与板端 Evidence。仅 Package 存在、镜像自检、离线契约或人工命令测试均不足以发布。HostAgent 未安装该 Release、无法回传受控 Evidence 或 Candidate revision 已改变时，状态必须为 `BLOCKED`，不得创建 Catalog、Binding 或 Worker。
# M5-A-R2 补充：S100 HostAgent 闭环

S100 `s100-runner-1.0.0` 以 Git 审核的固定发布物安装在 Host。控制面创建与 Candidate revision 绑定的验证任务；HostAgent 领取后只使用 16×16 fixture、锁定镜像和受保护板端 profile，回传 `.hbm / s100_hbm`、编译日志、板端预检、调用日志、profile 与结果。任务成功且 Evidence 完整前，Catalog、Binding、Worker 与用户 S100 入口均不得创建。
