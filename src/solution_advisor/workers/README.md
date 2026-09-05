# 平台无关 HostAgent

`solution_advisor.workers.worker_agent` 是运行在 Worker Host 的通用 Python
HostAgent。它负责以 Token 注册、周期心跳、领取已被控制面授予的任务、独立工作
目录、受控 Docker 调用和 Artifact/Evidence 回传；它不包含任一芯片的工具链
命令、镜像或规则。容量租约的事实来源属于控制面 PostgreSQL，HostAgent 不自行
伪造容量状态。

生产以 wheel 安装并由 systemd 启动：

```bash
solution-advisor-worker-agent --config /etc/solution-advisor/workers/x5-a/config.yaml
```

`--once` 用于开发验收。HostAgent 从实例配置的 `registration_token_file` 读取权限
0600 的专用 Token，并只通过控制面注册/心跳 API 上报自身；Token 不落数据库、
日志或界面。平台差异由各 `platform_packages/<平台>/worker-agent/` 配置和固定
Runner 提供；新增 J6M 只增加 J6M 平台包及实例配置，不复制 HostAgent。
