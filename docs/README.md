# RoboHarness 文档

本目录保存 RoboHarness 的架构、协议与开发规划。

## 当前文档

- [软件架构与分阶段 PR 开发规划](architecture-and-development-plan.md)：项目定义、运行架构、ROS 2 接口、生命周期、仓库与 Docker 结构、测试策略、逐 PR 路线图及依赖关系。
- [ADR 0001：开发平台基线](adr/0001-development-platform.md)：固定 Ubuntu 22.04、ROS 2 Humble、Python 3.10 和容器唯一开发路径。

## 文档约定

- 主规划是重构阶段的架构基线；实现 PR 应引用对应的 PR 编号和验收标准。
- 已确认决策若需变更，应在 `docs/adr/` 新增 ADR，而不是只在代码中隐式改变行为。
- 接口、配置 schema、结果 schema 或生命周期发生变化时，代码与文档必须在同一 PR 更新。
- 未来的操作手册、故障排查和发布说明分别放入 `docs/guides/`、`docs/troubleshooting/` 与 `docs/releases/`。
