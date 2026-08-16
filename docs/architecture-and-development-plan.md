# RoboHarness 软件架构与分阶段 PR 开发规划

- 状态：Proposed implementation baseline
- 目标版本：v0.1.0 MVP
- 适用范围：当前 monorepo 的首次实现
- 核心约束：稳定接口、简单实现；扩展型架构、MVP 级实现

本文将需求中 AD-1 至 AD-11 视为已确认决策，不重新选择三容器边界、数据路径或生命周期模型。若后续确需改变这些决策，必须通过 ADR 说明动机、兼容性与迁移方案。

---

## Part I — Project Definition

### 1.1 RoboHarness 是什么

RoboHarness 是一套机器人导航实验平台，由以下能力组成：

- Experiment Protocol 与 ROS 2 平台接口；
- Experiment / Episode 编排；
- Task 描述和 PointNav 参考实现；
- 旁路评估、事件记录与统一结果结构；
- Simulator / Robot / Agent 的集成 contract；
- 三容器部署工具及可测试的 reference implementations。

它定义“一个实现如何接入、如何准备一局、如何运行、如何结束及如何产出结果”，而不规定实现内部必须使用同一种 launcher、语言或类继承体系。

### 1.2 RoboHarness 不是什么

它不是某一个 simulator、robot driver 或 navigation algorithm，也不是把所有功能塞进一个 ROS package 的应用。MVP 不建设通用插件市场、分布式调度、Web UI、数据库、Kubernetes 或复杂 benchmark。

### 1.3 MVP 范围

唯一承诺的纵向组合是：

```text
Isaac Sim × Unitree Go2 × ROS 2 Keyboard Agent × PointNav × Simple Eval
```

成功标准不是“支持很多实现”，而是五个替换维度已建立清晰边界，且上述组合能稳定连续运行多个 Episode。

### 1.4 未来扩展维度

Simulator、Robot、Agent、Task、Evaluation 均通过 ROS contract、配置约定和目录边界扩展。MVP 使用显式 factory 和类型枚举，不建设动态插件注册、依赖注入框架或复杂继承树。

---

## Part II — Confirmed Architecture

### 2.1 运行结构

```text
                         ┌─────────────────────────────────┐
                         │           experiment            │
                         │ orchestrator / task / evaluator │
                         │ recorder                        │
                         └──────────┬──────────────┬───────┘
                                    │              │
                          control   │              │ evaluation
                          plane     │              │ plane
                                    v              v
                         ┌─────────────────┐   telemetry/results
                         │       env       │───────────────►
                         │ Isaac backend   │
                         │ + Go2 binding   │
                         └───────┬─────────┘
                                 │ observations
                                 v
                         ┌─────────────────┐
                         │      agent      │
                         │ keyboard agent  │
                         └───────┬─────────┘
                                 │ cmd_vel
                                 └──────────────► env
```

- Navigation Data Plane：`env ⇄ agent`，承载高频观测与 `cmd_vel`。
- Experiment Control Plane：`experiment` 协调 readiness、reset、task、start、abort 与状态。
- Evaluation Plane：evaluator 旁路观察状态和轨迹，不转发或修改控制命令。

### 2.2 三类生命周期必须解耦

| 层级 | 所有者 | 典型周期 | 作用 |
|---|---|---|---|
| Deployment | Docker Compose | 一次部署 | 启动网络、进程、挂载和 GPU |
| Component runtime | 各组件，orchestrator 观察 | 一次 Experiment，异常时可重启 | 初始化、ready、reset、error |
| Episode | experiment orchestrator | 一个 Experiment 内多次 | prepare、run、terminate、record |

进程存在不等于运行就绪，Episode 结束也不等于容器应退出。

---

## Part III — Responsibility Boundaries

| 模块 | Owns | Does not own |
|---|---|---|
| Env | 完整 Environment Backend：simulator、physics、world、robot binding、sensors、clock、底层运控、命令执行、env reset、非 RUNNING 时的最终速度门控 | agent policy、调度、指标汇总、结果持久化 |
| Agent | 消费标准观测、执行策略、输出命令、agent reset、任务局部状态；MVP 处理键盘输入 | simulator reset、spawn、Episode 调度、评估和持久化 |
| Experiment container | control/evaluation plane 的部署边界 | 高频导航数据转发、simulator 或 policy 实现 |
| Experiment Orchestrator | Experiment/Episode 权威状态、readiness 等待、reset 顺序、task 分配、start/abort、终止协调、失败策略 | 机器人实时控制、指标公式细节 |
| Task Manager | 加载并校验 EpisodeSpec、构造 PointNav task、start/goal/timeout/success 条件 | 控制 robot、判定组件 readiness、保存结果 |
| Evaluator | 订阅 ground truth/episode/task，维护轨迹并计算 metrics、提出终止候选 | 发布 `cmd_vel`、改变 world、决定调度策略 |
| Result Recorder | 原子写入 config、metadata、episode spec、events、trajectory、metrics 和 summary | 计算控制或拥有生命周期状态 |
| Simulator Backend | Isaac app/extension、timeline、stage、physics、world、原生 ROS 2 Bridge 配置与 backend readiness | Agent、Task/Eval、跨 simulator 的机器人声明 |
| Backend-local Robot Definition | 位于 `simulators/<sim>/robots/<robot>` 的 Go2 identity、frames、limits 与 asset manifest | 跨 backend 的全局 robot registry；MVP 不单独发布 robot package |
| Simulator × Robot Binding | Go2 asset spawn、articulation、传感器、`cmd_vel` 到 locomotion controller、joint/velocity reset、Isaac-specific physics 与安全门控 | Core protocol、Keyboard policy、跨 simulator 通用控制实现 |

安全速度门控由两端共同保证：Agent 在非 `RUNNING` 时停止发布并立即发零速度；Env 无条件拒绝/归零非 `RUNNING` 命令。Env 是最后安全边界，不能只信任 Agent。

---

## Part IV — Lifecycle Model

### 4.1 Component lifecycle

```text
STARTING ──initialized──► READY ──reset request──► RESETTING ──success──► READY
    │                       │                         │
    └────────failure───────►ERROR◄────failure────────┘
```

`RESETTING` 被保留，因为 Isaac reset 可能非瞬时；它使 readiness 含义明确。Env/Agent 分别拥有自己的 component state，orchestrator 只观察。状态消息必须包含 `component_id`、state、最近状态变化时间、错误码和简短 detail。

### 4.2 Experiment lifecycle

```text
CREATED -> STARTING -> RUNNING -> FINALIZING -> FINISHED
                  \                    /
                   └──────error──────► FAILED
```

orchestrator 是权威所有者。`STARTING` 等待配置和组件 readiness；`RUNNING` 可以包含多个 Episode；`FINALIZING` 生成 summary。不可恢复的基础设施错误进入 `FAILED`。

### 4.3 Episode lifecycle

```text
PREPARING -> READY -> RUNNING -> TERMINATING -> FINISHED
```

- `PREPARING`：验证 spec，Env reset，然后 Agent reset，分发 task，初始化 evaluator/recorder。
- `READY`：组件和任务均可运行，manual 模式等待用户；automatic 模式立即触发。
- `RUNNING`：允许控制闭环并累计 telemetry。
- `TERMINATING`：先 safe stop，再冻结 telemetry、计算指标和持久化。
- `FINISHED`：本 Episode 不再变化，允许进入下一局。

结果与状态正交：`state=FINISHED`，`termination_reason` 为 `SUCCESS | TIMEOUT | ABORTED | FAILURE | ENV_ERROR | AGENT_ERROR | INVALID_TASK`。MVP 不把 success/timeout 建模为生命周期状态。

每个状态迁移由 orchestrator 串行执行，携带单调递增的 `sequence` 和 `episode_id`；消费者忽略旧 episode 或旧 sequence 消息。

---

## Part V — Multi-Episode Execution

```text
load config -> wait env/agent READY
  -> for each EpisodeSpec:
       PREPARING
       -> reset env -> reset agent -> publish task
       -> READY -> manual/automatic start
       -> RUNNING -> success/timeout/abort/error
       -> TERMINATING -> safe stop -> evaluate -> persist
       -> FINISHED
  -> aggregate summary -> finish Experiment
```

- 容器和主要进程每个 Experiment 只启动一次；Episode 之间必须依赖 reset contract。
- Reset 请求携带 `episode_id` 和唯一 `request_id`，服务端应幂等：重复请求不得叠加重置。
- manual/automatic 仅改变 `READY -> RUNNING` 的触发源，其他路径共享实现。
- 单个 `INVALID_TASK`、timeout 或用户 abort 默认记录并继续下一局；reset 失败、组件 ERROR/crash、Isaac freeze 默认终止当前 Experiment，因为下一局的初始条件不可信。
- MVP 不自动重启容器。错误信息指出是否 `restart_required`，由操作人员重新部署；自动恢复留待有真实需求时设计。

---

## Part VI — Runtime Contracts

### 6.1 Env Contract

必须提供 component status、幂等 `reset_episode`、`cmd_vel` 输入、标准 observation、TF、simulation clock 与 Episode state awareness。READY 表示 Isaac、world、Go2 binding、physics、原生 ROS 2 Bridge 和必需接口全部可用。reset 成功表示 world、robot root/joint pose、velocity、locomotion controller 与 physics episode state 已恢复且输出为零。Go2 的底层运控属于 Env backend，不属于 Agent 或独立 robot driver。

### 6.2 Agent Contract

必须提供 component status、幂等 `reset_episode`、PointNav task 输入、Episode state awareness、所需标准 observations 和 `cmd_vel` 输出。Keyboard Agent reset 至少清除旧命令/局部状态并发布零速度。READY 表示可接受 reset/task 并能产生安全输出。

### 6.3 Experiment Contract

必须加载/校验 config，等待 readiness，拥有 Experiment/Episode 状态，按序 reset，分发 task，处理 start/abort/timeout/error，协调 safe stop、evaluation、recording 和多 Episode 迭代。它不得位于 observation/command 数据路径中。

### 6.4 实现机制

Core contract 由 ROS interfaces、配置 schema 和行为测试共同定义；Python `Protocol`/dataclass 只用于进程内 Task/Eval/Recorder 边界。MVP 不需要跨包抽象基类、动态 registry 或非 ROS RPC。

---

## Part VII — ROS 2 Interface Specification

### 7.1 命名和接口包

平台语义统一在 `/roboharness` 下；标准机器人接口使用 `/robot` namespace，以便未来多机器人时显式 remap：`/robot/cmd_vel`、`/robot/odom`、`/robot/imu`、`/robot/scan`、`/robot/camera/*`。`/tf`、`/tf_static` 和 `/clock` 保留 ROS 惯例。

自定义 `msg/srv` 全部置于独立 `rh_interfaces` package。接口定义不得依赖 Isaac、Go2 或 Python 实现包。

### 7.2 平台协议

| Name | Type | Publisher/server | Subscriber/client | Purpose / primitive rationale |
|---|---|---|---|---|
| `/roboharness/env/status` | `ComponentStatus.msg` topic | env | experiment | 连续/末值 readiness；topic 支持异步观察和 late join |
| `/roboharness/agent/status` | `ComponentStatus.msg` topic | agent | experiment | 同上 |
| `/roboharness/env/reset_episode` | `ResetEnv.srv` | env | experiment | 有明确请求、完成与错误结果，适合 service |
| `/roboharness/agent/reset_episode` | `ResetAgent.srv` | agent | experiment | 同上 |
| `/roboharness/episode/state` | `EpisodeState.msg` topic | experiment | env、agent、evaluator | 权威广播；多个消费者和 late join |
| `/roboharness/task/pointnav` | `PointNavTask.msg` topic | experiment | env、agent、evaluator | 同一不可变 task 快照直达多个消费者，不经 Env 转发 |
| `/roboharness/episode/start` | `StartEpisode.srv` | experiment | manual CLI/UI；automatic 内部调用同一 transition | 请求只负责接受/拒绝启动，不等待整局结束 |
| `/roboharness/episode/abort` | `AbortEpisode.srv` | experiment | CLI/operator | 明确确认 abort 是否被接受 |
| `/roboharness/episode/result` | `EpisodeResult.msg` topic | experiment | 可选报告工具 | 完成事件和摘要；持久化文件仍是事实来源 |

不使用长时 `RunEpisode.action`：Episode 的执行由状态 topic 观察，start/abort 是短请求，Action 会重复已有状态机。若未来出现远程客户端需要 goal/feedback/result 的明确所有权，再通过 ADR 引入。

### 7.3 初版自定义接口字段

- `ComponentStatus.msg`：`builtin_interfaces/Time stamp`、`string component_id`、`uint8 state`、`uint32 error_code`、`string detail`、`bool restart_required`；常量 `STARTING/RESETTING/READY/ERROR`。
- `EpisodeState.msg`：`stamp`、`experiment_id`、`episode_id`、`uint64 sequence`、`uint8 state`、`uint8 termination_reason`、`string detail`；定义生命周期和终止原因常量。
- `PointNavTask.msg`：`experiment_id`、`episode_id`、`geometry_msgs/PoseStamped start`、`goal`、`float64 success_radius_m`、`float64 timeout_s`、`int64 seed`。frame 必须相同且 MVP 为 `map`。
- `ResetEnv.srv` request：`request_id`、`experiment_id`、`episode_id`、`start`、`seed`；response：`success`、`error_code`、`detail`。
- `ResetAgent.srv` request：`request_id`、`experiment_id`、`episode_id`；response 同上。
- `StartEpisode.srv` request：`experiment_id`、`episode_id`；response：`accepted`、`detail`。
- `AbortEpisode.srv` request：IDs、`reason`；response：`accepted`、`detail`。
- `EpisodeResult.msg`：IDs、termination reason、success、elapsed time、path length、final distance、result URI。详细 schema 以 JSON 文件为准，避免 ROS message 膨胀。

### 7.4 标准 Data Plane

| Name | Type | Publisher | Subscriber | QoS |
|---|---|---|---|---|
| `/robot/cmd_vel` | `geometry_msgs/msg/Twist` | agent | env | reliable、volatile、keep_last 1 |
| `/robot/odom` | `nav_msgs/msg/Odometry` | env | agent/evaluator | sensor-data profile；允许 remap 为 reliable |
| `/robot/imu` | `sensor_msgs/msg/Imu` | env | agent/evaluator | sensor-data profile |
| `/robot/scan` | `sensor_msgs/msg/LaserScan` | env | agent | sensor-data profile |
| `/robot/points` | `sensor_msgs/msg/PointCloud2` | env | agent | sensor-data profile，MVP 可选 |
| `/robot/camera/*` | `sensor_msgs/msg/Image` + `CameraInfo` | env | agent | sensor-data profile，MVP 可选 |
| `/clock` | `rosgraph_msgs/msg/Clock` | env | all | ROS simulation-time convention |
| `/tf`, `/tf_static` | TF2 | env | agent/evaluator | TF2 默认 QoS |

所有节点设置 `use_sim_time=true`。最小 TF 树为 `map -> odom -> base_link -> sensor frames`；谁拥有每条 transform 必须唯一，禁止多发布者冲突。

### 7.5 QoS、超时和发现

- status、episode state、PointNav task、episode result：reliable + transient_local + keep_last 1。
- reset/start/abort：service 默认 reliable；客户端有显式 discovery timeout 和 call timeout。
- 高频 sensor：ROS sensor-data QoS；`cmd_vel` depth 1，Env 还应实现 simulation-time command watchdog。
- 默认单机同一 `ROS_DOMAIN_ID`，三个 service 共享 Docker network；固定同一 RMW 实现。若 DDS multicast 在主机/容器环境不可用，提供版本化 Fast DDS/Cyclone DDS discovery 配置，而不是引入第二套协议。

---

## Part VIII — Task Model

```text
Experiment
  └─ ordered Episode instances
       ├─ immutable EpisodeSpec
       │    ├─ Scenario/world reference
       │    ├─ Task(type=pointnav, start, goal)
       │    ├─ timeout/success radius
       │    └─ seed
       ├─ lifecycle state
       └─ termination reason/result
```

- Experiment：一次配置和部署上下文下的有序 Episode 集合。
- EpisodeSpec：运行前已校验、运行中不可变的一局输入描述。
- Episode：EpisodeSpec 的一次执行，拥有状态、事件和结果。
- Scenario：world/scene 与可选静态参数的引用，不等同于 Task。
- Task：目标语义；MVP 只有 PointNav，不创建深层继承结构。
- Termination Condition：goal distance、timeout、abort 或 runtime error；orchestrator 汇总候选并决定唯一 reason。

MVP YAML：

```yaml
schema_version: 1
experiment:
  name: go2_keyboard_pointnav
  execution_mode: manual
  episodes:
    - episode_id: "0000"
      scenario: warehouse_default
      task:
        type: pointnav
        start: {frame_id: map, x: 1.0, y: 2.0, yaw: 0.0}
        goal: {frame_id: map, x: 8.0, y: 4.0, yaw: 0.0}
        success_radius_m: 0.5
        timeout_s: 120.0
      seed: 42
```

配置加载后转换为 typed dataclass，并一次性完成不依赖环境的静态验证：唯一 ID、有限数值、正 timeout/radius 和 frame 一致。静态无效配置直接拒绝启动 Experiment；依赖已加载 world 的检查（例如 start/goal 是否处于有效区域）在对应 Episode 的 PREPARING 阶段执行，失败时以 `INVALID_TASK` 结束该局且不允许机器人运动。

---

## Part IX — Evaluation Architecture

数据分层：

1. Raw telemetry：按固定频率采样的 timestamp、pose，可选 collision signal；不默认复制全部 camera/lidar。
2. Events：状态迁移、reset、task、start、goal reached、timeout、abort、errors，JSONL 追加写。
3. Metrics：从 telemetry/spec 计算的单局数值。
4. Episode result：spec、termination reason、metrics、artifact references 和完整性状态。
5. Experiment summary：总局数、成功/失败/超时计数及聚合指标。

MVP metrics：`success`、`elapsed_time_s`、`path_length_m`、`final_distance_to_goal_m`、`timeout`、`termination_reason`。只有 Isaac 能低成本稳定提供碰撞事件时才加入 `collision_count`，它不阻塞 v0.1。

计算约定：使用 simulation time；path length 对 `map` frame 的采样 pose 做相邻欧氏距离累加，剔除 reset 跳变且记录采样频率；success 是 RUNNING 期间首次满足 goal distance 阈值。evaluator 产生终止候选，orchestrator 提交权威终止状态。

结果布局：

```text
results/<experiment_id>/
├─ config.yaml
├─ metadata.json
├─ episodes/
│  ├─ 0000/
│  │  ├─ episode.yaml
│  │  ├─ trajectory.csv
│  │  ├─ events.jsonl
│  │  └─ metrics.json
│  └─ 0001/...
└─ summary.json
```

此结构已经足够简单。Recorder 先写临时文件再原子 rename；`metadata.json` 记录 schema version、git SHA、image digests、ROS distro、Isaac version、开始/结束时间。即使失败也尽力写出带 `complete=false` 的 result。

---

## Part X — Repository Structure

采用 domain-oriented monorepo。`simulators`、`agents`、`tasks`、`evaluators` 是四个同级扩展维度；共享平台代码集中在 `packages`。源码不按 Docker service 或传统 `ros2_ws/src` 组织，Colcon 直接从多个 base paths 发现 ROS packages。

内部 ROS/Python package 使用简短 `rh_` 前缀；项目名称、文档术语和公共 ROS namespace 仍使用 `RoboHarness`、`/roboharness`，避免公共接口含义不清或与其他系统冲突。

```text
roboharness/
├─ README.md
├─ LICENSE
├─ pyproject.toml                       # repo-level Python/lint tooling
├─ colcon.defaults.yaml                 # Colcon build/install/log defaults
├─ .github/
│  ├─ workflows/ci.yaml
│  └─ pull_request_template.md
│
├─ packages/                            # 平台内部与通信相关包
│  ├─ rh_interfaces/                    # ament_cmake: msg/srv only
│  ├─ rh_core/                          # ament_python: ROS-independent domain
│  ├─ rh_ros/                           # ament_python: ROS transport helpers
│  └─ rh_experiment/                    # orchestrator + recorder
│
├─ simulators/                          # Simulator backends；Robot 位于内部
│  └─ isaac_sim/
│     ├─ apps/
│     │  └─ rh.kit                      # 启用原生 Bridge 与项目 extension
│     ├─ extensions/
│     │  └─ rh.isaac/
│     │     ├─ config/extension.toml
│     │     └─ rh/isaac/
│     ├─ bridge/
│     │  ├─ action_graphs/              # 原生 ROS 2 Bridge graph 定义
│     │  └─ topics.yaml                 # topic/frame/QoS mapping
│     ├─ robots/
│     │  └─ go2/                        # Isaac Sim × Go2 完整 binding
│     │     ├─ config/
│     │     ├─ assets/
│     │     ├─ assets.lock
│     │     ├─ spawn.py
│     │     ├─ locomotion.py
│     │     ├─ sensors.py
│     │     ├─ reset.py
│     │     ├─ safety.py
│     │     └─ bridge_graph.py
│     └─ tests/
│
├─ agents/
│  └─ keyboard/                         # package: rh_agent_keyboard
├─ tasks/
│  └─ pointnav/                         # package: rh_task_pointnav
├─ evaluators/
│  └─ simple_navigation/                # package: rh_eval_simple_navigation
│
├─ configs/
│  ├─ experiments/mvp.yaml
│  ├─ scenarios/warehouse_default.yaml
│  ├─ agents/keyboard.yaml
│  ├─ tasks/pointnav.yaml
│  └─ simulators/isaac_sim_go2.yaml
│
├─ deployment/                          # 部署的权威定义
│  ├─ README.md                         # mounts、profiles、commands、host 要求
│  ├─ compose/
│  │  ├─ compose.yaml                  # headless production/default
│  │  ├─ compose.gui.yaml              # Isaac GUI + interactive keyboard
│  │  └─ compose.mock.yaml             # CPU-only CI
│  ├─ docker/
│  │  ├─ env/
│  │  │  ├─ Dockerfile
│  │  │  └─ entrypoint.sh
│  │  ├─ agent/
│  │  │  ├─ Dockerfile
│  │  │  └─ entrypoint.sh
│  │  └─ experiment/
│  │     ├─ Dockerfile
│  │     └─ entrypoint.sh
│  ├─ env/
│  │  ├─ .env.example
│  │  └─ versions.env                  # ROS/Isaac/image version pins
│  └─ dds/
│     ├─ fastdds.xml
│     └─ README.md
│
├─ tests/
│  ├─ fixtures/
│  │  ├─ mock_env/                     # package: rh_mock_env
│  │  └─ mock_agent/                   # package: rh_mock_agent
│  ├─ contracts/
│  ├─ integration_mock/
│  ├─ integration_isaac/
│  └─ e2e/
├─ tools/
│  ├─ dev/
│  └─ validation/
├─ docs/
│  ├─ README.md
│  ├─ architecture-and-development-plan.md
│  ├─ adr/
│  ├─ guides/
│  └─ troubleshooting/
├─ logs/                                # gitignored service logs
└─ results/                             # gitignored experiment output
```

### 10.1 `packages`: platform internals

- `rh_interfaces` 是三个容器共享的 wire contract，只包含 RoboHarness 实验语义 `msg/srv`，没有 node 或实现代码。
- `rh_core` 包含 Experiment/Episode typed models、配置、状态机、termination policy 和 result schema；核心模块不得 import `rclpy`、Isaac 或具体 implementation。
- `rh_ros` 只实现 QoS、status heartbeat、reset idempotency、service timeout、Episode sequence guard 和 message/model conversion，不拥有业务状态。
- `rh_experiment` 实现 orchestrator、Task/Evaluator 装配和 recorder。MVP 使用一个主要 ROS node，Task Manager、Evaluator、Recorder 优先作为进程内对象。

依赖只能向稳定层流动：

```text
rh_interfaces       rh_core
       \              /
              rh_ros
                 \
              rh_experiment -> selected task/evaluator
```

`rh_interfaces` 和 `rh_core` 不依赖 simulator、agent、task 或 evaluator；具体实现不得被 `packages` 静态反向引用，选择发生在配置/factory 组合点。

### 10.2 Four peer extension domains

四个一级目录表达五维模型中的四个可见实现域，其中 Robot 是 Simulator backend 的子域：

```text
simulators/<simulator>/robots/<robot>
agents/<agent>
tasks/<task>
evaluators/<evaluator>
```

新增实现使用明确配置 ID 和小型 factory/entry point 选择，不建设动态插件市场。MVP 只创建 `isaac_sim/robots/go2`、`keyboard`、`pointnav` 和 `simple_navigation`。Task/Evaluator 不得 import simulator backend；Agent 只能依赖公开 ROS data plane 和 platform contract。

每个 leaf implementation 可以是独立 ament/Python package，但父目录不是 package。这允许 Agent 后续分别携带 Nav2、PyTorch 或 VLA runtime，而不污染平台依赖。

### 10.3 Isaac Sim backend and Go2 ownership

Env 的可执行实现为：

```text
Environment Backend = Isaac Sim runtime + Go2 binding
```

`simulators/isaac_sim` 不是普通 ROS adapter package。`rh.kit` 与 `rh.isaac` extension 管理 timeline、stage、physics、world、readiness、Episode reset 和 safety。标准 sensors、TF、clock、command transport 使用 Isaac Sim 原生 `isaacsim.ros2.bridge` OmniGraph/Action Graph nodes；项目只保存官方方式下的 graph、topic/frame 配置和必要的 lifecycle glue，不复制 ROS 2 Bridge。Bridge publishers/subscribers/services 只在 simulation playback 时活跃，因此 Env READY 必须验证 timeline 正在运行且所需 Action Graph 已激活。[Isaac Sim ROS 2 Bridge](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.bridge/docs/index.html)

`simulators/isaac_sim/robots/go2` 拥有完整低层仿真实现：asset、spawn、articulation、sensor prim、`cmd_vel` 到 locomotion controller、root/joint state reset、physics 参数与最终安全门控。Agent 只输出平台控制命令，不承担 Go2 底层运控。

当前不创建顶层 `robots/` 或 `rh_go2` package。未来增加 `Gazebo + Go2` 时，在 `simulators/gazebo/robots/go2` 实现对应 binding；只有出现经过验证的跨 simulator 复用代码后，才将纯数据或模型提取到 `packages/rh_robot_model`，避免为理论复用预先制造抽象。

Isaac backend 的实现以官方能力为准：通过 Kit/extension dependency 启用 Bridge；通过 `isaacsim.ros2.nodes` 提供的 OmniGraph nodes 建立 publisher/subscriber/service graph；需要精确控制发布频率时采用 Standalone/OnImpulseEvent 工作流；timeline、entity/world 等通用控制优先评估官方 `isaacsim.ros2.sim_control`，RoboHarness 只补充原子 Episode reset 与 Go2 controller state 等平台语义。参考：[ROS 2 Bridge](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.bridge/docs/index.html)、[ROS 2 Nodes](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.nodes/docs/index.html)、[Standalone Workflow](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/tutorial_ros2_python.html)、[Simulation Control](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.ros2.sim_control/docs/index.html)。

### 10.4 Build domains without `ros2_ws`

| Domain | Content | Tooling |
|---|---|---|
| Platform / ROS | `packages/`、`agents/`、`tasks/`、`evaluators/`、`tests/fixtures/` | Colcon / ament |
| Isaac Backend | Kit app、extension、Action Graph、Go2 binding | Isaac Sim / Kit extension system |

推荐构建命令：

```bash
colcon build \
  --base-paths packages agents tasks evaluators tests/fixtures \
  --build-base .build/colcon/build \
  --install-base .build/colcon/install
```

Isaac Kit extension 不伪装成 ROS package，由 `simulators/isaac_sim/apps/rh.kit` 加载。`colcon.defaults.yaml` 固定 `.build/colcon/*`，根目录保持整洁。

### 10.5 Deployment ownership

`deployment` 是“如何构建和运行三个容器”的唯一权威位置：

- `compose/*.yaml` 定义 services、build context、network、profiles、ports/devices 和 volumes。
- `docker/<service>/Dockerfile` 定义镜像依赖与安装内容；`entrypoint.sh` 只负责 source 环境并 exec service 命令，不承载业务状态机。
- `env/.env.example` 列出用户必须配置的 host paths、`ROS_DOMAIN_ID`、display/GPU 选项；`versions.env` 固定 ROS/Isaac/image versions。
- `dds/` 保存容器通信所需的 middleware 配置；仅在目标部署验证需要时启用。
- `deployment/README.md` 列出 prerequisites、mount contract、headless/GUI/mock 命令和故障排查入口。

Compose 中的 build context 固定为仓库根目录，Dockerfile 使用 `deployment/docker/...`：

```yaml
services:
  env:
    build:
      context: ../..
      dockerfile: deployment/docker/env/Dockerfile
```

`deployment/compose/compose.yaml` 位于仓库根目录下两层，因此 `../..` 指向 monorepo root。Compose 文件直接声明挂载，不再建立第二份 mounts 配置：

| Host/source | Container target | Mode | Consumer |
|---|---|---|---|
| `configs/` | `/opt/rh/configs` | read-only | all |
| `simulators/isaac_sim/` | `/opt/rh/simulators/isaac_sim` | image copy；dev 时 read-only mount | env |
| `results/` | `/data/results` | read-write | experiment |
| `logs/<service>/` | `/data/logs` | read-write | corresponding service |
| named Isaac caches | NVIDIA/Omniverse cache paths | read-write | env |

权威运行命令：

```bash
# One-time local deployment settings
cp deployment/env/.env.example deployment/env/.env

# Headless
docker compose --env-file deployment/env/.env \
  -f deployment/compose/compose.yaml up --build

# GUI + manual keyboard
docker compose --env-file deployment/env/.env \
  -f deployment/compose/compose.yaml \
  -f deployment/compose/compose.gui.yaml up --build

# CPU mock CI/local smoke
docker compose --env-file deployment/env/.env \
  -f deployment/compose/compose.mock.yaml up --build --abort-on-container-exit
```

可在 `tools/dev/` 提供薄 wrapper，但上述 Compose 命令必须始终可直接执行，wrapper 不复制 volume/profile/business logic。

### 10.6 Tests and assets

- Simulator-specific USD、sensor、controller assets 放在 `simulators/<simulator>/robots/<robot>`；只提交允许再分发的文件，否则保存 URL、checksum、license 和 fetch instructions。
- 每个 leaf package 的 unit tests 放在自身 `test/`；顶层 `tests/` 只保存跨 package、跨进程和跨容器验证。
- Mock Env/Agent 位于 `tests/fixtures`，严格作为 CPU protocol fixtures，不进入 production registry。

---

## Part XI — Docker Architecture

### 11.1 Services and images

```yaml
services:
  env:        # Isaac Sim app + native ROS 2 Bridge + Go2 binding; NVIDIA runtime
  agent:      # Keyboard Agent; interactive stdin in manual profile
  experiment: # orchestrator + task + evaluator + recorder
```

每个 service 可以启动多个同容器模块，但 MVP 优先减少进程数：`experiment` 初期使用一个 ROS node 加进程内 Task/Evaluator/Recorder 模块；只有独立故障隔离或 QoS 需求出现后才拆 node。

- 使用显式 image tags 和 base image versions，不使用 floating `latest`。
- `compose.yaml` 是 headless 默认；`compose.gui.yaml` 只增加 display、GUI 和输入设备映射，不改变 ROS protocol。
- 共享只读 config volume；results/logs 分别写入宿主目录；assets 对 env 只读。
- 仅 env 获取 GPU、NVIDIA runtime 和 Isaac EULA/缓存挂载；agent/experiment 不获得 GPU。
- Compose healthcheck 只用于“进程/容器还活着”的部署诊断，不能替代 ROS readiness。

镜像内容按运行边界选择，而不是按仓库目录一一复制：

| Image | Installed content |
|---|---|
| `env` | `rh_interfaces`、必要的 `rh_ros`、Isaac Kit app/extension、原生 `isaacsim.ros2.bridge`、Isaac Sim × Go2 binding |
| `agent` | `rh_interfaces`、`rh_ros`、`rh_agent_keyboard` |
| `experiment` | `rh_interfaces`、`rh_core`、`rh_ros`、`rh_experiment`、`rh_task_pointnav`、`rh_eval_simple_navigation` |

Env 的高频数据平面由 Isaac 原生 ROS 2 Bridge Action Graph 直接发布/订阅；RoboHarness extension 不再创建一套平行的 camera/lidar/odom/cmd transport，只负责 graph 配置、backend readiness、Episode reset 和安全语义。

三个服务位于同一用户定义 bridge network，统一 `ROS_DOMAIN_ID`、`RMW_IMPLEMENTATION`、`ROS_LOCALHOST_ONLY=0`、`use_sim_time=true`。先验证 multicast discovery；仅在目标平台确有问题时加入固定 DDS discovery server/profile。DDS 配置是部署细节，不改变 topic/service names。

| Mount | Mode | Consumer | Purpose |
|---|---|---|---|
| `configs/` | read-only | all | experiment/env/agent config |
| `simulators/isaac_sim/` | image copy；dev override read-only | env | Kit app、extension、Go2 binding 与 assets |
| `results/` | read-write | experiment | durable result artifacts |
| `logs/<service>/` | read-write | each service | runtime diagnostics |
| Isaac caches | read-write | env | shader/content cache acceleration |

开发源码 bind mount 只放在可选 dev override，发布运行使用镜像内构建产物，避免宿主状态污染复现性。

---

## Part XII — Startup and Readiness

```text
docker compose up
  -> services/processes start
  -> env=STARTING, agent=STARTING
  -> experiment subscribes status before acting
  -> env=READY and agent=READY
  -> orchestrator prepares Episode 0
```

Env 只有在 Isaac、stage、Go2、physics、ROS bridge、clock、required topics/services 均可用后发布 READY。Agent 只有在 node、subscriptions、publisher、reset service 和 task/state inputs 均建立后发布 READY。status 使用 transient local，周期心跳 1 Hz；状态变化立即发布。

配置提供 `startup_timeout_s`、`status_stale_timeout_s`、`reset_timeout_s`、`safe_stop_timeout_s`，禁止硬编码 `sleep 20/30`。建议 MVP 默认分别为 300、5、30、2 秒，Isaac startup timeout 可配置增大。Startup 使用 wall/steady clock，因为 simulation clock 可能尚未前进；Episode timeout 使用 simulation time，同时以 wall-clock watchdog 检测 Isaac freeze。

| Failure | Detector | Episode result | Continue | Restart required |
|---|---|---|---|---|
| Env never READY / stale / crash | status deadline | `ENV_ERROR` | no | yes |
| Agent never READY / stale / crash | status deadline | `AGENT_ERROR` | no | yes |
| Env reset fails/times out | service response/deadline | `ENV_ERROR` | no | usually |
| Agent reset fails/times out | service response/deadline | `AGENT_ERROR` | no | usually |
| Isaac clock freezes | wall-clock watchdog | `ENV_ERROR` | no | yes |
| No `cmd_vel` | Env watchdog/event | 保持零速，最终可 timeout | yes | no |
| Episode timeout | evaluator/orchestrator | `TIMEOUT` | yes | no |
| Invalid goal/spec | Task Manager | `INVALID_TASK` | configurable, default yes | no |
| User abort | abort service | `ABORTED` | yes | no |

任何异常首先触发 Env 侧零速度门控，再 finalize 可用 artifacts。MVP 不做分布式重试；reset 请求最多在确认幂等后重发一次，用于响应丢失而不是掩盖真实错误。

---

## Part XIII — PointNav MVP

PointNav EpisodeSpec 必须包含唯一 ID、`map` frame 中的 start/goal、positive success radius、positive timeout、seed 和 execution mode。yaw 用于初始姿态，MVP success 只判断平面位置距离，不要求目标朝向。

1. Task Manager 在运动前验证 schema 和有限数值。
2. Env reset 到 start 并确认 robot 静止；Agent reset；task 直接发布到 Env/Agent/Evaluator。
3. Episode 进入 READY，manual 模式等待 `/episode/start`。
4. RUNNING 后 Keyboard Agent 才能驱动；Evaluator 计算 goal distance。
5. 距离首次 `<= success_radius_m` 为 `SUCCESS`；simulation elapsed `>= timeout_s` 为 `TIMEOUT`。
6. 同时发生时优先级为 runtime safety error、user abort、success、timeout；最终 reason 只提交一次，其他候选作为事件保存。

MVP 不包含 SPL、语义目标、动态场景、复杂碰撞惩罚或 start/goal 自动采样。

---

## Part XIV — Testing Architecture

| Layer | Scope | Runner |
|---|---|---|
| Unit | config、state transitions、metric math、serialization、failure policy | CPU CI |
| Interface | rosidl build、字段/常量、依赖、schema examples | CPU CI |
| Mock ROS integration | status QoS、service timeout/idempotency、task/state propagation | CPU CI + ROS 2 |
| Multi-Episode | reset order、无进程重启、无状态泄漏、结果隔离 | CPU CI + mocks |
| Compose smoke | 三个 CPU mock services 的 network/discovery/startup | Docker CI |
| Isaac integration | stage、Go2 reset、clock、TF、sensors、cmd_vel gate | GPU self-hosted/manual/nightly |
| MVP E2E | GUI keyboard、多 Episode、metrics/results | GPU 人工；稳定后 nightly |

Mock Env/Agent 是 protocol test fixture，不是第二 simulator。它们必须 CPU-only、deterministic、fast，并支持注入 readiness delay、reset error、crash/stale status、motion trajectory 和 timeout。

CPU CI 至少执行 `colcon build`、lint/type checks、unit/interface tests、mock readiness/reset、3 局连续执行且 PID 不变、task propagation、success/timeout/abort/error、result schema 和非 RUNNING 零速度保护。每个 Isaac PR 必须记录 image/Isaac/GPU 版本、人工步骤、预期 topic/TF/status、实际结果及日志证据；GPU 尚未自动化时，此证据是 merge gate。

---

## Part XV — Development Roadmap

路线按依赖拆为四个 Milestone。M0 固化边界，M1 用 mock 打通平台核心，M2 接入真实 Env/Agent，M3 集成并发布。M1 与 M2 在 core protocol 稳定后并行，避免等所有 mock 工作完成才第一次发现 Isaac 集成风险。

### Milestone M0 — Repository and Protocol Foundation

#### PR 01 — Repository Foundation

**Goal:** 建立所有后续 PR 共用、可构建和可审查的 monorepo 骨架。  
**Changes:** 初始化 domain directories、`colcon.defaults.yaml`、repo tooling、基础 CI、lint、`.gitignore`、PR template 和各域 README。  
**Out of Scope:** 自定义 ROS 接口、runtime node、Docker/Isaac 功能。  
**Files / Modules:** 根目录、`.github/`、`packages/`、四个扩展域、`deployment/`、`tests/`、`docs/`。  
**ROS Interfaces:** 无。  
**Tests:** 对多个 base paths 执行 `colcon list/build/test`，以及 Markdown/link/basic YAML checks。  
**Acceptance Criteria:** 新 clone 可按文档在目标 ROS 2 distro 构建；CI 绿色；目录与 Part X 一致。  
**Dependencies:** 无。  
**Risks:** ROS distro/Ubuntu 版本未锁定导致后续漂移；本 PR 必须在 `docs/adr` 记录版本基线。  
**After this PR:** 仓库是可持续合并小 PR 的最小工程，而不是功能实现。

#### PR 02 — Core ROS Interfaces

**Goal:** 固化平台语义的最小 wire contract。  
**Changes:** 创建 `rh_interfaces`，实现 Part VII 的 msg/srv、常量和接口说明。  
**Out of Scope:** publisher/server/client 实现；通用 Observation message；Action。  
**Files / Modules:** `packages/rh_interfaces/`、`tests/contracts/`、docs。  
**ROS Interfaces:** `ComponentStatus`、`EpisodeState`、`PointNavTask`、`EpisodeResult`、`ResetEnv`、`ResetAgent`、`StartEpisode`、`AbortEpisode`。  
**Tests:** rosidl build、field/constant contract tests、dependency lint。  
**Acceptance Criteria:** C++/Python typesupport 可生成；接口不依赖实现 package；示例消息可 round-trip。  
**Dependencies:** PR 01。  
**Risks:** 过早扩张接口；所有字段必须能由 MVP 用例证明。  
**After this PR:** Env/Agent/Experiment 可以针对同一协议独立开发。

#### PR 03 — Core Models and Configuration

**Goal:** 建立 ROS-independent 的 Experiment/Episode/PointNav 配置与状态模型。  
**Changes:** typed models、YAML loader、schema version、validation、termination priority 和 state transition guards。  
**Out of Scope:** ROS node、实际编排、metrics、Docker。  
**Files / Modules:** `packages/rh_core/`、`configs/experiments/`、unit tests。  
**ROS Interfaces:** 只提供 model-to-message 映射测试，不增加接口。  
**Tests:** valid/invalid YAML、transition table、duplicate IDs、NaN/frame/timeout 校验。  
**Acceptance Criteria:** 示例 MVP config 一次性校验通过；非法 transition/配置返回结构化错误。  
**Dependencies:** PR 02。  
**Risks:** domain model 与 wire model 重复；映射集中在单一 adapter module。  
**After this PR:** 不启动 ROS 也能测试核心实验语义。

#### PR 04 — Runtime Protocol Helpers

**Goal:** 将 readiness、reset、state/task QoS 和 timeout 约定实现为可复用薄层。  
**Changes:** status publisher/monitor、idempotent reset guard、QoS profiles、service deadline helpers、stale heartbeat detection。  
**Out of Scope:** Mock/Isaac/Keyboard 行为和 orchestrator state machine。  
**Files / Modules:** `packages/rh_ros/`、launch tests。  
**ROS Interfaces:** 实现 PR 02 的 status/reset/state/task transport 语义。  
**Tests:** late join、heartbeat stale、duplicate request ID、timeout、QoS compatibility。  
**Acceptance Criteria:** helper 无 simulator/robot dependency；行为与 Part VII/XII 一致。  
**Dependencies:** PR 02、PR 03。  
**Risks:** helper 变成框架；只封装重复且有 contract 价值的代码。  
**After this PR:** reference components 可用一致方式实现 runtime contract。

### Milestone M1 — CPU-Testable Vertical Slice

#### PR 05 — Mock Env Fixture

**Goal:** 用 deterministic CPU fixture 验证 Env contract。  
**Changes:** Mock Env status/reset、simulation clock、odom/TF、cmd_vel watchdog、Episode state gate、故障注入。  
**Out of Scope:** physics realism、Gazebo、Isaac compatibility layer。  
**Files / Modules:** `tests/fixtures/mock_env/`、integration tests。  
**ROS Interfaces:** Env status/reset、Episode state、`/clock`、`/robot/cmd_vel`、odom/TF。  
**Tests:** readiness、idempotent reset、start pose、non-RUNNING zero gate、freeze/reset failure injection。  
**Acceptance Criteria:** headless 测试 < 30 s 且 deterministic；fixture 明确标注不可作为 simulator 产品实现。  
**Dependencies:** PR 04。  
**Risks:** mock 与真实 contract 偏离；接口测试共享同一 black-box suite。  
**After this PR:** Env 一侧协议无需 GPU 即可验证。

#### PR 06 — Mock Agent Fixture

**Goal:** 用 deterministic fixture 验证 Agent contract 和任务状态隔离。  
**Changes:** Mock Agent status/reset/task/state subscriptions、可配置轨迹命令、故障注入。  
**Out of Scope:** Keyboard input、planner、学习策略。  
**Files / Modules:** `tests/fixtures/mock_agent/`、integration tests。  
**ROS Interfaces:** Agent status/reset、PointNav task、Episode state、`cmd_vel`。  
**Tests:** reset 清状态、非 RUNNING 不驱动、task episode ID 过滤、crash/stale status。  
**Acceptance Criteria:** 重复 Episode 不泄漏 command/task state；测试 deterministic。  
**Dependencies:** PR 04。  
**Risks:** 轨迹逻辑侵入平台；将其限制为测试脚本化行为。  
**After this PR:** Agent 一侧协议可在 CPU CI 独立验证。

#### PR 07 — Single-Episode Orchestrator

**Goal:** 实现一个 Episode 的权威状态机与 readiness/reset/start/abort 协调。  
**Changes:** orchestrator node、Experiment startup、状态广播、reset order、manual start、termination commit、safe-stop handshake。  
**Out of Scope:** 多 Episode loop、真实 evaluator、完整 recorder、Isaac。  
**Files / Modules:** `packages/rh_experiment/orchestrator`、launch tests。  
**ROS Interfaces:** status clients、reset clients、Episode state publisher、start/abort servers。  
**Tests:** happy path、非法 start、abort、stale component、reset timeout、一次性 termination。  
**Acceptance Criteria:** 使用 stub components 完成 PREPARING 到 FINISHED；orchestrator 是唯一 state publisher。  
**Dependencies:** PR 04。  
**Risks:** callback 并发竞态；所有 transition 经单线程 event queue/guard。  
**After this PR:** 平台已有可观察的单局生命周期。

#### PR 08 — PointNav Task Module

**Goal:** 实现首个具体 Task，不引入万能 Task hierarchy。  
**Changes:** PointNav validation、task builder/publisher、goal distance/timeout condition definitions、示例 configs。  
**Out of Scope:** evaluator aggregation、自动 goal sampling、其他 Task。  
**Files / Modules:** `tasks/pointnav/`、configs、tests。  
**ROS Interfaces:** publish `PointNavTask`，验证 direct subscribers 和 transient-local behavior。  
**Tests:** start/goal/frame/radius/timeout、late subscriber、episode mismatch。  
**Acceptance Criteria:** Env/Agent/Evaluator 可直接获得同一不可变 task；非法 goal 在运动前拒绝。  
**Dependencies:** PR 03、PR 04。  
**Risks:** Task 与 Eval 耦合；只共享 typed spec/termination predicate，不共享 recorder。  
**After this PR:** 生命周期可以携带真实 PointNav 语义。

#### PR 09 — Simple Evaluation

**Goal:** 以旁路 observer 计算 PointNav MVP metrics。  
**Changes:** trajectory sampler、goal/timeout candidates、metric functions、simulation-time handling。  
**Out of Scope:** recorder、碰撞指标、控制命令干预。  
**Files / Modules:** `evaluators/simple_navigation/`、unit/integration tests。  
**ROS Interfaces:** subscribe task/state/odom/clock；向 orchestrator 提交进程内 termination candidate。  
**Tests:** path length、success radius、timeout、reset jump exclusion、out-of-order stamps。  
**Acceptance Criteria:** Part IX 指标对固定轨迹给出稳定结果；模块从不 publish `cmd_vel`。  
**Dependencies:** PR 07、PR 08。  
**Risks:** sim time 停止导致挂起；wall watchdog 由 orchestrator 处理并有测试。  
**After this PR:** 单局能产生可验证的导航指标。

#### PR 10 — Result Recorder

**Goal:** 按稳定 schema 持久化失败和成功实验。  
**Changes:** metadata/events/trajectory/metrics/summary writers、atomic writes、schema version。  
**Out of Scope:** 数据库、对象存储、rosbag、分析 UI。  
**Files / Modules:** `packages/rh_experiment/recorder`、result schema tests。  
**ROS Interfaces:** 可选 publish `EpisodeResult`；文件为事实来源。  
**Tests:** exact directory layout、JSON/YAML schema、partial failure、path sanitization、atomic replace。  
**Acceptance Criteria:** 中断也留下可解析 `complete=false` artifacts；正常结果可由独立 reader 校验。  
**Dependencies:** PR 03；可与 PR 05–09 并行。  
**Risks:** 写入阻塞 ROS callback；通过 buffered module/终止阶段写入控制。  
**After this PR:** 实验输出可复现、可追踪、可机器读取。

#### PR 11 — Multi-Episode and Failure Policy

**Goal:** 用运行中组件连续执行多局并实现最小失败策略。  
**Changes:** Episode loop、per-episode cleanup、summary、continue/stop policy、status/clock watchdog、完整 recorder wiring。  
**Out of Scope:** 自动进程重启、并行 Episode、分布式容错。  
**Files / Modules:** orchestrator/core/recorder integration、mock tests。  
**ROS Interfaces:** 不新增；验证既有 reset/state/task/result contract。  
**Tests:** ≥3 Episodes、PID 不变、无状态泄漏、success/timeout/abort/invalid task、component/reset failure。  
**Acceptance Criteria:** 正常多局不重启任何 service；每局独立 artifacts，summary 计数正确。  
**Dependencies:** PR 05、06、07、08、09、10。  
**Risks:** cleanup 竞态和旧消息污染；使用 episode ID、sequence、barrier 和测试延迟消息。  
**After this PR:** RoboHarness Core 已在 mock vertical slice 中完整打通。

#### PR 12 — CPU Mock Compose and CI E2E

**Goal:** 在与生产相同的三 service 边界验证部署和 DDS discovery。  
**Changes:** CPU mock Compose profile、Dockerfiles/entrypoints、volume/network config、CI smoke job。  
**Out of Scope:** GPU、Isaac image、GUI。  
**Files / Modules:** `deployment/compose/compose.mock.yaml`、`deployment/docker/`、CI/tools。  
**ROS Interfaces:** 不新增；黑盒检查 graph 和 artifacts。  
**Tests:** compose up/down harness、readiness、3 Episodes、service PID/container ID stability、result export。  
**Acceptance Criteria:** 单条 CI 命令在干净 runner 完成 mock experiment；无固定 sleep。  
**Dependencies:** PR 11。  
**Risks:** nested Docker runner 不稳定；job 可独立标记但必须是 protected required check。  
**After this PR:** 三容器部署边界在 CPU 环境得到端到端证明。

### Milestone M2 — Reference Runtime Integration

#### PR 13 — Isaac Backend and Native ROS 2 Bridge Skeleton

**Goal:** 尽早验证 Isaac Kit backend、官方 ROS 2 Bridge、DDS 和容器 GPU 风险。  
**Changes:** pinned env image、`rh.kit`、`rh.isaac` extension skeleton、headless/GUI launcher、启用 `isaacsim.ros2.bridge`、clock/Action Graph smoke、manual validation script。  
**Out of Scope:** Go2 spawn/control、完整 reset、MVP E2E。  
**Files / Modules:** `simulators/isaac_sim/apps/`、`extensions/`、`bridge/`、`deployment/docker/env/`、Compose env profile、GPU tests。  
**ROS Interfaces:** STARTING/ERROR status；READY 暂不承诺，或仅在 smoke mode 使用明确 capability detail。  
**Tests:** image build、GPU launch、stage/clock/native Bridge/ROS discovery manual or self-hosted smoke。  
**Acceptance Criteria:** 锁定可复现 Isaac/driver/ROS 版本；外部容器能看到 Isaac 原生 Bridge ROS graph；项目未复制 sensor/cmd ROS bridge；验证记录齐全。  
**Dependencies:** PR 04；可与 PR 05–12 并行。  
**Risks:** Isaac/ROS distro/GPU driver compatibility 是最高外部风险，应早期暴露。  
**After this PR:** 首个 Isaac/GPU 依赖点已被隔离并验证。

#### PR 14 — Isaac Sim × Go2 Binding and Locomotion

**Goal:** 在 Isaac backend 内实现 Go2 asset、传感器和底层仿真运控，不创建独立 Go2 runtime package。  
**Changes:** asset manifest/license、Isaac spawn、articulation、`cmd_vel` 到 locomotion controller、sensor/physics config、Bridge Action Graph wiring。  
**Out of Scope:** Keyboard Agent、multi-Episode orchestration changes、Gazebo binding。  
**Files / Modules:** `simulators/isaac_sim/robots/go2/`、`simulators/isaac_sim/bridge/`、GPU tests。  
**ROS Interfaces:** 通过 Isaac 原生 Bridge 暴露 odom/imu/scan/TF/cmd_vel，保持 Part VII names/types。  
**Tests:** asset/license check、TF uniqueness、spawn pose、zero command、manual GPU motion smoke。  
**Acceptance Criteria:** Go2 在 Isaac 中可 spawn 并由 Twist 驱动；标准 Data Plane 可见；底层 controller 位于 simulator binding；不修改 Core interface。  
**Dependencies:** PR 13。  
**Risks:** asset redistributability、controller semantics；以 manifest/license 和限幅测试缓解。  
**After this PR:** Isaac Sim × Go2 真实数据与低层运控闭环成立。

#### PR 15 — ROS 2 Keyboard Agent

**Goal:** 实现 MVP 人工控制 reference Agent，并完整遵守 Agent contract。  
**Changes:** keyboard mapping、terminal handling、status/reset/task/state、zero command、command rate/limits。  
**Out of Scope:** GUI framework、Nav2、autonomy、evaluation。  
**Files / Modules:** `agents/keyboard/`、`deployment/docker/agent/`、agent config、tests。  
**ROS Interfaces:** Agent status/reset、PointNav/state subscriptions、`/robot/cmd_vel` publisher。  
**Tests:** key mapping、reset clears command、non-RUNNING zero、terminal cleanup、mock integration。  
**Acceptance Criteria:** 丢焦点/abort/reset/exit 均产生安全零速度；无需 Isaac 可完成大部分测试。  
**Dependencies:** PR 04、PR 08；可与 PR 13–14 并行。  
**Risks:** Docker TTY/input portability；明确支持矩阵并将输入 adapter 与 agent logic 分离。  
**After this PR:** MVP Agent 可接入 mock 或真实 Env。

#### PR 16 — Isaac Go2 Env Contract

**Goal:** 使真实 Env 达到 READY/reset/safe-gate 的完整平台 contract。  
**Changes:** readiness probes、idempotent reset、world/root/joint pose、velocity、locomotion controller 与 physics reset、Episode gate、watchdogs、error mapping。  
**Out of Scope:** 新 robot/simulator、复杂 scene、自动 restart。  
**Files / Modules:** `simulators/isaac_sim/extensions/rh.isaac/`、`simulators/isaac_sim/robots/go2/reset.py`、env deployment、GPU integration tests。  
**ROS Interfaces:** 完整 Env status/reset/state/data plane。  
**Tests:** 两次以上 reset、pose/velocity verification、clock/TF、non-RUNNING command rejection、freeze/error manual cases。  
**Acceptance Criteria:** 多次 reset 不重启 Isaac；每次 start state 在容差内；READY 含义满足 Part VI/XII。  
**Dependencies:** PR 14。  
**Risks:** Isaac reset 残留 physics/sensor state；定义容差、settling condition 和观测验证，而非固定 sleep。  
**After this PR:** 真实 Env 可替换 Mock Env 而不改 Core。

### Milestone M3 — MVP Integration and Release

#### PR 17 — MVP End-to-End Integration

**Goal:** 打通唯一承诺的 Isaac × Go2 × Keyboard × PointNav × Simple Eval 纵向路径。  
**Changes:** production Compose/config、GUI manual profile、integration wiring、操作/验收手册、bug fixes limited to contract compliance。  
**Out of Scope:** 新 feature、性能重构、第二 implementation。  
**Files / Modules:** `deployment/`、configs、guides、e2e tests；必要的现有 package 小修。  
**ROS Interfaces:** 不新增，任何变更需单独 protocol PR/ADR。  
**Tests:** ≥3 manual PointNav Episodes，无容器/Isaac 重启；success、timeout、abort；结果与 summary 校验。  
**Acceptance Criteria:** 从干净环境按文档启动；全部 readiness/reset/state/safety/result 标准通过；记录 GPU 验收证据。  
**Dependencies:** PR 11、12、15、16。  
**Risks:** integration PR 膨胀；发现的非集成修复拆为前置小 PR。  
**After this PR:** MVP 功能完成并达到 release candidate。

#### PR 18 — Hardening, Documentation and v0.1 Release

**Goal:** 将已完成 MVP 转为可重复使用和可维护的 v0.1.0。  
**Changes:** fresh-install verification、failure runbook、schema/interface freeze notes、license/SBOM、release notes、tag workflow。  
**Out of Scope:** 第二 simulator/agent/task/eval、新 UI。  
**Files / Modules:** docs、CI/release、LICENSE/NOTICE、version metadata。  
**ROS Interfaces:** 冻结 v0.1 contract，不新增。  
**Tests:** 全部 CPU gates、fresh GPU E2E、artifact checksums、文档命令验证。  
**Acceptance Criteria:** Part XVII 的 MVP/v0.1 DoD 全部满足；已知限制明确；可创建 signed/annotated `v0.1.0` tag。  
**Dependencies:** PR 17。  
**Risks:** 文档与镜像漂移；从 tag/build metadata 生成版本并做 clean-room 验证。  
**After this PR:** v0.1.0 可发布，后续用第二 implementation 验证抽象。

---

## Part XVI — Git Workflow

### 16.1 Branch and merge strategy

- `main` 受保护：禁止直接 push，要求 PR、required checks、至少一名 reviewer（单人维护阶段允许 author 在检查完成后 merge，但保留 PR 记录）。
- 分支使用 `feat/<scope>`、`fix/<scope>`、`docs/<scope>`、`ci/<scope>`，短期存在，合并后删除。
- 推荐 **Squash Merge**：路线图中的每个 PR 是一个独立、可回滚的逻辑能力；squash 能使 `main` 历史与 PR 边界一致。PR 内仍保留有意义的小 commit 方便 review。
- 禁止把 protocol、多个大型 component、Docker 集成和 E2E 混在一个 PR。接口破坏性变更需要 ADR、迁移说明和相应测试。

### 16.2 Commit convention

使用 Conventional Commits：`feat`、`fix`、`refactor`、`test`、`docs`、`build`、`ci`、`chore`。建议 scope：`protocol`、`core`、`experiment`、`task`、`eval`、`env`、`isaac`、`go2`、`agent`、`docker`。

```text
feat(protocol): define component status interfaces
feat(experiment): add multi-episode orchestrator
fix(env): reject commands outside running episode
test(eval): cover reset discontinuity in path length
```

### 16.3 PR template

每个 PR 必填：Motivation、Scope、Architecture Changes、Implementation、Testing、Acceptance Criteria、Known Limitations、Follow-up。Isaac PR 额外附 GPU 环境、手工验收和证据。描述必须链接本文 PR 编号；偏离计划时说明原因。

### 16.4 Tags and releases

- 开发阶段不为每个 PR 打 tag；M0/M1 完成可用 annotated pre-release tag `v0.1.0-alpha.1`、`v0.1.0-beta.1`，仅在团队确需共享构建时创建。
- MVP 验收后创建 annotated `v0.1.0`，release notes 列出 image digests、ROS/Isaac/GPU 支持矩阵、interface/result schema version 和已知限制。
- v0.1 后采用 SemVer；ROS interface 或结果 schema 的不兼容变化至少提升 minor（0.x 阶段）并提供迁移说明。

---

## Part XVII — Definition of Done

### PR Done

- Scope/Out of Scope 与实现一致，无未解释架构漂移；
- build、lint、相关 unit/integration tests 全部通过；
- 新 failure path 有结构化错误、safe behavior 和测试；
- 用户可见 config/interface/result 变化同步文档；
- acceptance criteria 有可复查证据，仓库合并后仍可构建和回滚。

### Milestone Done

- 该 Milestone 所有必需 PR Done，跨 PR 集成测试通过；
- 文档中的运行命令由干净环境验证；
- 未解决事项进入明确 issue/后续 PR，不用 TODO 隐藏 release blocker。

### MVP Done

- 只有 `env`、`agent`、`experiment` 三个 runtime services，职责符合本文；
- Env/Agent 直接交换 observations/`cmd_vel`，Experiment 不在闭环中；
- Env/Agent readiness 与 reset contract 生效，禁止固定 sleep；
- Isaac + Go2 + Keyboard + PointNav + Simple Eval 连续执行至少 3 局且不重启组件；
- success、timeout、abort 和至少一个 component error 路径经验证；
- 每局输出 metrics/termination reason/artifacts，Experiment 输出 summary；
- 非 RUNNING 命令被 Agent 和 Env 双重归零/拒绝；
- CPU mock CI 绿色，真实 GPU E2E 有可复查证据。

### v0.1 Done

除 MVP Done 外，还要求 clean-room 安装/运行验证、版本锁定、LICENSE/NOTICE 和第三方 asset 审计、发布说明、已知限制、接口与结果 schema version、镜像 digest/SBOM，以及 `v0.1.0` annotated tag。

---

## Part XVIII — Architecture Extension Check

| Extension | 应新增 | 可修改 | 不应修改 |
|---|---|---|---|
| New Simulator | `simulators/<name>/` backend、其原生 ROS bridge 配置、至少一个 `robots/<robot>` binding、env image/profile、integration tests | simulator selection、部署文档 | `agents/`、PointNav、Eval、Episode protocol |
| New Robot | 各目标 backend 下的 `simulators/<sim>/robots/<robot>`、asset manifest、低层控制/reset/sensor binding | simulator config、标准 topic/frame remaps | Experiment state machine、Task/Eval contract；MVP 不新增顶层 robot package |
| New Agent | `agents/<name>` package/config/image entry、contract tests | agent factory/Compose selection | Env、Task forwarding、orchestrator data path |
| New Task | `tasks/<name>` model/message（确有不同语义时）、validation、termination tests | Task Manager factory、config schema version | Env↔Agent 数据平面、既有 PointNav contract |
| New Eval | `evaluators/<name>`、metrics/result schema extension、tests | evaluator factory、summary fields | robot control、Episode ownership、Env reset |

审查规则：第二 implementation 若要求修改 Core，首先判断是 contract 缺陷、implementation detail 泄漏，还是确有跨实现通用能力。只有前两者修复或经 ADR 证明的通用语义才可改变 Core；不得为单个 integration 特例污染协议。

最有价值的验证顺序是 second Agent → second Simulator（建议 Gazebo + Go2）→ second Robot → second Task → second Eval。Gazebo + Go2 应保持 Agent、PointNav、Evaluator 和 Experiment protocol 不变。

---

## Part XIX — Recommended First PR

第一项实现 PR 应是 **PR 01 — Repository Foundation**。

先做它的原因：当前仓库为空，后续 interface、mock 和 Isaac 工作都需要统一 ROS distro、构建命令、目录、CI 与 review 规则。它提供可验证底座，同时不把尚未被代码检验的 protocol 设计与大量 scaffolding 一次绑定。

它不实现 ROS interface、runtime node、Docker image、Isaac、Go2 或 Keyboard Agent，也不声称完成任何实验能力。

具体 acceptance criteria：

1. 初始化 Git monorepo 和 Part X 的必要空骨架，但不提交无意义 placeholder package。
2. 锁定并记录 Ubuntu、ROS 2、Python 与基础构建工具版本；Isaac 兼容矩阵可先标记待 PR 13 验证。
3. 新 clone 按 README 可执行依赖安装、`colcon build` 和 `colcon test`。
4. CPU CI、Markdown/YAML checks 与 PR template 生效。
5. `main` 保护、Squash Merge 和 Conventional Commits 约定写入贡献文档。
6. PR 合并后仓库可构建、可测试，无任何伪装成完成实现的 stub 行为。

---

## Part XX — PR Dependency Graph

```text
PR01 Repository Foundation
 └─ PR02 Core ROS Interfaces
     └─ PR03 Core Models / Config
         └─ PR04 Runtime Protocol Helpers
             ├─ PR05 Mock Env ───────────────┐
             ├─ PR06 Mock Agent ─────────────┤
             ├─ PR07 Single-Episode Orch ────┤
             ├─ PR08 PointNav ──┬─ PR09 Eval ┤
             │                  └─ PR15 Keyboard Agent ──────────────┐
             └─ PR13 Isaac/Bridge ── PR14 Go2 Binding ─ PR16 Env ───┤
PR03 ─────────── PR10 Recorder ─────────────────┐                    │
                                                v                    │
PR05 + PR06 + PR07 + PR08 + PR09 + PR10 ──> PR11 Multi-Episode     │
                                                │                    │
                                                v                    │
                                      PR12 Mock Compose/CI ──────────┤
                                                                     v
                                                        PR17 MVP Integration
                                                                     │
                                                                     v
                                                        PR18 v0.1 Release
```

- Integration critical path：PR01 → PR02 → PR03 → PR04 后分成 M1、PR08/PR15 与 PR13/PR14/PR16 三条并行链，最终在 PR17 汇合，再到 PR18。PR17 同时等待 PR11/12、PR15 和 PR16；实际工期的关键链取决于 GPU backend 与 M1 两者中较慢的一支。
- Parallelizable：PR05/06/07；PR10 与 PR05–09；PR13 与 M1；PR15 与 PR13–16。
- First Isaac-dependent PR：PR13。
- First GPU-dependent PR：PR13（手工或 self-hosted smoke）。
- Core protocol proof gate：PR11；在此之前不宣称 multi-Episode architecture 已成立。
- MVP integration PR：PR17；它不得新增 protocol，只组合已验证能力。

### 计划执行原则

接口统一不等于 Docker 实现相同；process startup、runtime readiness、Episode lifecycle 永远分别处理。若进度受限，优先保证 responsibility boundaries、stable contracts、testability、loose coupling、ROS-native semantics 和 simplicity，再考虑扩展性与性能优化。
