# 平台治理模块

本目录维护平台从“发现镜像”到“可调度执行能力”的治理事实。平台不是由 Docker
镜像名称自动推断出来的；只有经过接入验证和审核发布的目录项，才能被用户评估流程
选择。

## 核心对象

```text
HostAgent（Host 在线与发现事实）
→ HostImage（镜像观察事实）
→ PlatformCandidate（管理员接入草稿）
→ PlatformCatalog（已审核的平台类型 + 版本 + Runner Release）
→ PlatformBinding（某 Host 承载某 Catalog 的授权关系）
→ PlatformWorker（Binding 下的逻辑执行能力与容量）
```

- `PlatformCatalog` 以平台类型和版本唯一；发布后用于冻结评估 Flow 的平台规则。
- `PlatformBinding` 记录健康、能力、容量、镜像校验和固定 Runner Release。
- `PlatformWorker` 是可领取受控任务的逻辑执行器，不等于长期运行的编译容器。
- `PlatformCandidate` 只用于管理员接入工作流，不允许普通用户访问或直接调度。

## 调度与安全边界

- 用户只能选择已发布且可调度的 Catalog，不能提交 Worker、镜像、命令、Docker 参数、
  板端地址、路径或凭据。
- 评估创建时冻结 Catalog、Binding、Worker、Runner、镜像锁、规则与解析器；任务领取
  必须再次校验快照，不得因发布新版本而改投到其他平台版本。
- 同一 `(HostAgent, image_digest)` 仅允许一个活跃 Candidate；镜像发现本身不会自动创建
  Candidate、Catalog、Binding 或 Worker。
- Candidate 的处理权由管理员主动领取和释放；超级管理员可带审计原因接管。

平台接入流程、跨 Host 复用和容量说明见 `docs/design/平台接入与扩展手册.md`。
