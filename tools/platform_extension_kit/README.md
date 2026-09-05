# 平台接入与扩展套件

此套件将平台接入手册落成可重复执行的起点：生成标准包结构、提供受控 Runner 与镜像自检脚本范例、离线可用性检查，以及 `result.json` 的安全摘要工具。它可用于“候选镜像预筛通过后”的待接入平台，不会把发现到的 Docker 镜像自动变成可调度平台。

它不下载或启动镜像，不访问网络、板卡、SSH，也不调用厂商工具链。生成骨架更不等同于平台已完成编译、板端验证、性能验证或可交付部署。

## 快速开始

在仓库根目录执行：

```bash
uv run python tools/platform_extension_kit/create_platform.py \
  --platform-id j6m --display-name J6M \
  --output platform_packages/j6m

uv run python tools/platform_extension_kit/check_platform.py platform_packages/j6m
```

生成器只创建不存在的目录；若目标已经存在会拒绝覆盖，避免误伤已接入的平台包。

## 生成内容与用途

| 内容 | 必需性 | 用途与缺失影响 |
| --- | --- | --- |
| `manifest.yaml` | 必需 | 平台 ID、能力和受限结论边界；缺失则控制面不能安全识别平台。 |
| `rules/rules.yaml` | 必需 | 平台事实规则的唯一归属；缺失会使静态分析没有审查入口。 |
| `docker/image.lock.yaml` | 必需 | 受审查镜像和固定入口的锁定位置；不得包含凭据。 |
| `runner/platform_runner/` | 必需 | 短时任务容器中的受控执行入口；模板只提供静态检查。 |
| `worker-agent/instance.config.example.yaml` | 必需 | 通用 Agent 部署某个平台实例所需的非秘密配置形状。 |
| `scripts/self_check_image.sh` | 必需 | 人工触发的镜像存在与工具版本自检模板；不会自动执行。 |
| `tests/static-request.json` | 必需 | 可重复的最小 Runner 输入。 |
| `reports/` | 必需 | 平台报告字段扩展说明；不应把未验证结论写成事实。 |
| 真实编译/板端脚本 | 可选且后续实施 | 仅在完成厂商工具审查和对应里程碑后添加；不能由模板伪造。 |

## 推荐接入流程

```text
Agent 发现候选镜像并由管理员预筛
        ↓
创建待接入平台记录 → 收集厂商资料与边界
        ↓
生成平台包骨架 → 填写 manifest、规则、镜像锁定与受限 Runner
        ↓
执行离线契约检查 → 人工执行镜像自检（有 Docker 权限时）
        ↓
补充平台静态测试 → 审核发布 PlatformCatalog → 创建 Agent PlatformBinding
        ↓
由通用 Agent 在该 Binding 下创建/复用 Worker 并领取任务
        ↓
后续里程碑再引入已审查的编译、板端与 REAL 证据能力
```

## 工具说明

### 1. 脚手架生成

`create_platform.py` 生成完整最小结构和可参考的 Runner、配置、镜像自检脚本。它不会覆盖已有目录。

### 2. 离线可用性检查

```bash
uv run python tools/platform_extension_kit/check_platform.py platform_packages/<platform-id>
```

检查文件齐全性、平台 ID 一致性、能力白名单、请求 SHA256 以及 M4-A 的板端边界；不依赖 Docker 或外网。

### 3. 镜像自检模板

```bash
bash platform_packages/<platform-id>/scripts/self_check_image.sh <locked-image@sha256:...>
```

接入者先将脚本中的 `<vendor-tool> --version` 改成固定的厂商工具版本命令。脚本刻意不接受任务提供的命令，避免变成任意命令入口。

### 4. 结果调试摘要

```bash
uv run python tools/platform_extension_kit/debug_result.py /path/to/result.json
```

它只展示状态、阶段、产物/证据计数和验证边界，不打印原始 URI、日志或潜在敏感内容。

## 与现有 X5 包的关系

`platform_packages/x5` 是已接入的参考实现；本套件提炼的是通用结构与安全边界，不复制任何厂商规则、镜像、工具命令或结论。接入 J6M 等新平台时，应以厂商正式资料填充自己的平台事实，并遵循 [平台接入与扩展手册](../../docs/design/平台接入与扩展手册.md)。
