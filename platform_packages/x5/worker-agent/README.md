# x5-a Worker Host 安装边界

生产 Worker Host（执行服务器）目录固定为：`/opt/solution-advisor/worker-agent/`、
`/opt/solution-advisor/platform-packages/x5/`、
`/etc/solution-advisor/workers/x5-a/config.yaml`、
`/etc/solution-advisor/secrets/x5-a/`、`/var/lib/solution-advisor/worker/x5-a/work/`
与 `/var/log/solution-advisor/worker/x5-a/`。注册令牌只能存在于受限的密钥文件
（权限 0600）或 systemd `EnvironmentFile`，不写入 Git、任务、日志或报告。

Agent 仅接受控制面签发并完成容量检查的固定任务；它以周期心跳维持实例可见，
再用只读输入和独立输出目录运行锁定镜像中的 `python -m platform_runner`。禁止把用户
提供的镜像、Docker 参数、挂载、网络、Shell 命令或宿主机路径转交给 Docker。
本阶段没有 SSH、板卡连接、性能或精度验证。

安装通用 Agent wheel 后，以本包的 `x5-a.config.example.yaml` 生成 `/etc` 实例
配置，再由 systemd 运行：

```bash
solution-advisor-worker-agent --config /etc/solution-advisor/workers/x5-a/config.yaml
```

开发单次处理使用相同 Agent：

```bash
solution-advisor-worker-agent --config /etc/solution-advisor/workers/x5-a/config.yaml --once
```

这里没有 X5 专用 Agent 源码：通用 Agent 只读取配置并执行受 Platform Package
锁定的 Runner。J6M 等新平台复用同一 wheel，仅提供自己的平台包和实例配置。
