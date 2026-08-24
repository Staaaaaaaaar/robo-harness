# RoboHarness

RoboHarness 是面向机器人导航任务的快速实验、自动运行与统一评估平台。它通过稳定的 ROS 2 运行协议，将 Simulator、Robot、Agent、Task 与 Evaluation 解耦，并以可复现的 Experiment / Episode 模型组织实验。

> Architecture for extension, implementation for MVP.

## 当前状态

项目正在逐步实现 MVP。当前已经提供可复现的 monorepo 开发环境、核心协议、
实验协调与结果记录，以及由三个独立容器组成的 CPU mock 参考运行链。MVP
严格限定为：

- Simulator：NVIDIA Isaac Sim
- Robot：ANYmal C
- Agent：ROS 2 Keyboard Agent
- Task：PointNav
- Evaluation：Simple Navigation Evaluation
- Runtime：`env`、`agent`、`experiment` 三个 Docker Compose service

## 核心架构

```text
                       experiment
              orchestration + evaluation
                    /              \
           control plane       evaluation plane
                  /                  \
                 v                    v
              env  <-------------- telemetry
               | ^
  observations | | cmd_vel
               v |
              agent
```

`env` 与 `agent` 通过 ROS 2 直接构成导航闭环；`experiment` 负责 readiness、任务分配、Episode 生命周期、评估与结果持久化，不进入实时控制数据路径。

一个 Experiment 可以连续运行多个 Episode。容器和进程每个 Experiment 启动一次，Episode 之间通过显式 reset contract 复用组件，不依赖重启容器。

## 文档

- [文档索引](docs/README.md)
- [软件架构与分阶段 PR 开发规划](docs/architecture-and-development-plan.md)

上述规划是当前实现工作的权威基线。若实现需要改变已确认的架构决策，应先提交 ADR 与文档 PR。

## 开发环境

唯一受支持的开发路径是 Ubuntu 22.04、ROS 2 Humble、Python 3.10 的 CPU
开发容器。宿主机只需 Git、Docker Engine、Docker Compose v2 和 Make，不需
安装 ROS 2。

```bash
make dev-image
make dev-check
```

交互式开发：

```bash
make dev-shell
make build-local
source .build/colcon/install/setup.bash
make test-local
```

常用宿主机入口：

```bash
make dev-list
make dev-build
make dev-test
make dev-lint
```

运行并验证三容器 CPU mock 链路：

```bash
make mock-e2e
```

PR13 的 Isaac backend / 原生 ROS 2 Bridge 骨架使用：

```bash
cp deployment/env/.env.example deployment/env/.env
# 阅读 NVIDIA EULA 后，将 ACCEPT_EULA 改为 Y。
make isaac-config
make isaac-smoke
```

本地 Linux X11 图形会话可直接运行：

```bash
make isaac-gui
```

首次配置 GPU 开发机请按
[PR13 Isaac 开发环境与调整记录](docs/guides/isaac-pr13-development-environment.md)
区分宿主机、运行基线和本地 consent 配置，再执行
[NVIDIA Container Toolkit 安装指南](docs/guides/nvidia-container-toolkit-host-setup.md)。

开发容器只是临时工具环境，不属于 RoboHarness 的运行服务。详细说明见
[部署与开发环境](deployment/README.md)和
[开发平台 ADR](docs/adr/0001-development-platform.md)。

## CPU mock 运行方式

`make mock-e2e` 会构建精简 runtime 镜像，启动 `env`、`agent`、`experiment`
三个独立容器，等待 ROS 图和三个 Episode 结果完成，校验产物后自动清理服务。
结果和容器日志保存在 `.build/mock-e2e/`。

当前 Isaac profile 只验证 pinned image、Kit application、原生 Bridge、`/clock`
与跨容器 DDS discovery；它不包含 ANYmal C、运控、完整 Env reset 或 MVP E2E。
完整运行方式仍将在 PR14–PR17 中补齐。

运行链：

```text
services start
  -> env / agent READY
  -> prepare and reset Episode
  -> manual start
  -> navigate and evaluate
  -> persist results
  -> next Episode without restarting services
```

## 开发约定

- 容器内执行 Colcon、测试和 lint；CI 使用同一个开发镜像和 `make dev-check`。
- 使用 feature branch 与 Pull Request，保护 `main`。
- Commit 遵循 Conventional Commits。
- 推荐使用 Squash Merge，使一个 PR 对应一个可回滚的逻辑变更。
- 每个 PR 必须保持可构建、可测试、职责单一，并更新受影响文档。
- CPU CI 使用 mock components 覆盖平台协议；Isaac / GPU 测试放在手工、自托管或 nightly 流程。

完整贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 非目标

MVP 不实现 Gazebo、Nav2、Reactive/RL/VLA/VLN Agent、其他机器人、复杂 benchmark、通用插件框架、Web UI、数据库、分布式调度或 Kubernetes。

## License

License 尚未确定。在明确许可证之前，请勿假定仓库内容可被再分发；引入 ANYmal C/Isaac 资源时也必须单独核对其许可证与再分发条件。
