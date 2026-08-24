# PR13 Isaac 开发环境与调整记录

本文把 PR13 开发过程中确认的宿主机环境、仓库配置、实现调整和最终验证结果
整理在一起。新开发者应先阅读本文了解全貌，再按
[NVIDIA Container Toolkit 宿主机配置](nvidia-container-toolkit-host-setup.md)
完成安装，最后执行
[PR13 验证流程](isaac-pr13-validation.md)。

本文记录的是一次可复现的验证快照，不把某台工作站的软件包版本误当成所有
开发者必须采用的唯一版本。项目真正固定的运行边界保存在
`deployment/env/versions.env`；宿主机驱动、Docker 和 Toolkit 仍需在每台机器上
单独验证。

## 1. 环境分层

PR13 涉及四个相互独立的配置层：

| 层 | 负责内容 | 权威位置 |
| --- | --- | --- |
| 宿主机 | NVIDIA 驱动、Docker Engine、Compose、Container Toolkit、CDI | 操作系统与 Docker daemon |
| 固定运行基线 | Isaac/ROS 镜像、digest、ROS domain、参考机器人 | `deployment/env/versions.env` |
| 开发者本地选择 | EULA、隐私选择、headless/GUI、`DISPLAY` | 被 Git 忽略的 `deployment/env/.env` |
| 仓库实现 | Kit App、Extension、Bridge graph、Compose、smoke harness | `simulators/isaac/`、`deployment/`、`tools/` |

CPU 开发容器不需要 NVIDIA GPU、原生 ROS 2、CUDA Toolkit 或 Isaac Lab。只有
启动 `compose.isaac.yaml` 中声明了 `gpus: all` 的 Isaac `env` service 时，Docker
才必须通过 NVIDIA Container Toolkit 将宿主机 GPU 和匹配的驱动库注入容器。
构建镜像本身不执行 GPU 仿真，因此不应把“镜像构建成功”等同于“GPU 运行已
验证”。

## 2. 当前固定基线

- 宿主机/容器平台：Ubuntu 22.04 x86_64
- ROS：ROS 2 Humble，Python 3.10
- Isaac Sim：4.5.0，镜像按 manifest digest 固定
- ROS middleware：`rmw_fastrtps_cpp`
- 验证用 ROS domain：42
- Robot：ANYmal C，具体 binding 属于后续 PR14
- Locomotion：计划使用 Isaac Sim 自带策略
- Isaac Lab：不属于 MVP runtime，不安装

`ACCEPT_EULA=Y` 表示实际运行容器的人已经阅读并接受 NVIDIA Omniverse EULA；
RoboHarness 不会代替操作者设置它。`PRIVACY_CONSENT=Y` 是独立的数据收集选择，
默认保持 `N`，接受 EULA 不代表同时同意数据收集。

## 3. 本次宿主机验证快照

2026-08-24 的通过证据来自
`.build/isaac-smoke/20260824T083123Z-112676/`：

| 项目 | 通过时的值 |
| --- | --- |
| Host OS | Ubuntu 22.04.5 LTS, x86_64 |
| Kernel | `6.8.0-138-generic` |
| NVIDIA driver | `580.173.02` |
| NVIDIA Container Toolkit CLI/library | `1.20.0` |
| Docker Engine | `29.7.2` |
| Docker Compose | `5.5.0` |
| Isaac Sim | `4.5.0`，固定 digest |
| ROS domain | `42` |
| 结果 | 外部 Humble observer 收到原生 `/clock`，PASS |

驱动 580.173.02 是这台 kernel 6.8 工作站的已验证版本，不是项目最低版本。
其他满足 Isaac Sim 4.5 官方要求的驱动可以使用，但必须重新运行 smoke 并记录
证据。升级驱动后必须重启宿主机；仅完成 DKMS 安装还不能证明新内核模块已经
加载。

## 4. 从新机器到通过 smoke

先验证宿主机驱动：

```bash
uname -m
cat /etc/os-release
uname -r
nvidia-smi
```

然后安装和配置 Toolkit。完整命令及 rootless、WSL2、Jetson、远程 Docker
差异见专门指南；rootful Docker 的关键步骤是：

```bash
sudo apt-get install --yes nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
nvidia-ctk cdi list
docker run --rm --gpus all ubuntu:22.04 nvidia-smi
```

最后配置并验证仓库：

```bash
cp deployment/env/.env.example deployment/env/.env
# 阅读 EULA 后编辑 deployment/env/.env，将 ACCEPT_EULA 改为 Y。
make isaac-config
make isaac-smoke
```

`make isaac-smoke` 会构建固定镜像、启动 Isaac `env` 和验证专用 observer、等待
真实 `/clock` 数据、检查 Env status topic 与容器重启次数，并在退出时清理
Compose services。每次运行的日志和环境信息保存在新的
`.build/isaac-smoke/<UTC token>/` 中。

## 5. PR13 开发过程中确认的调整

### 5.1 不引入 Isaac Lab

最初规划同时保留 Isaac Sim 和 Isaac Lab。确认 MVP 直接使用 Isaac Sim 自带的
ANYmal C locomotion policy 后，PR13 runtime 移除了 Isaac Lab 依赖。以后只有在
明确需要训练、导出或转换 policy 时，才单独选择并固定对应工具版本。

### 5.2 使用基础 App 加增量配置

项目没有把 `isaacsim.exp.base` 当作普通 Extension 依赖。容器实际启动
`/isaac-sim/apps/isaacsim.exp.base.kit`，再通过
`--merge-config=<project rh.kit>` 合并项目 App 配置，同时注册 NVIDIA apps 和
项目 Extension 搜索目录。容器以 root 运行 Kit 时显式传入 `--allow-root`。

### 5.3 复用 Isaac 自带的 ROS 2 Humble 库

启动脚本执行 Isaac 的 `setup_python_env.sh`，设置 `ROS_DISTRO=humble`、
`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`，并把 Bridge 内置 ROS 2 library path 与
构建好的 `rh_interfaces` overlay 暴露给 Kit。项目没有在 Isaac 镜像内再安装一
套完整 ROS desktop，也没有复制实现 ROS 2 Bridge。

### 5.4 等待 Kit ready 后初始化仿真

`rh.isaac` Extension 等待 `EVENT_APP_READY`，异步创建 `SimulationContext`，然后
创建并启动 clock graph。Kit 保持 update/render loop 的所有权，Extension 负责
RoboHarness 生命周期 glue，避免在 Extension 内启动第二套主循环。

### 5.5 使用原生 OmniGraph 发布仿真时钟

`/clock` graph 使用 `OnPlaybackTick`、`ROS2Context`、
`IsaacReadSimulationTime` 和 `ROS2PublishClock`。这与 NVIDIA 官方工作流一致；
Bridge publisher 只有在 timeline playback 时才活跃。

### 5.6 Linux 验证栈共享 host network 与 IPC

Isaac `env` 和验证 observer 使用 host network，并在这项限定的 Fast DDS smoke
中共享 host IPC。仅发现 `/clock` publisher 不足以证明数据可用；验收条件是外部
observer 实际收到一条 `rosgraph_msgs/msg/Clock`。

### 5.7 将宿主机故障与项目故障分层

开发早期出现的 `failed to discover GPU vendor from CDI` 发生在容器启动前，
原因属于 Toolkit/CDI/Docker 设备发现层。处理顺序固定为：

```text
host nvidia-smi
  -> nvidia-container-cli / CDI
  -> generic docker --gpus all probe
  -> Isaac container
  -> Kit App / Extension
  -> ROS 2 Bridge /clock
```

在上游层未通过前，不调试 `rh.isaac` 代码，也不通过把宿主机 driver/CUDA 库
复制进镜像来绕过设备注入。

## 6. 当前验证边界

PR13 PASS 只证明：固定 Isaac Sim 镜像能使用该宿主机 GPU 启动，项目 Kit App
和 Extension 能加载，外部 ROS 2 Humble observer 能收到原生 `/clock`，并能发现
`/roboharness/env/status`。

它不证明 ANYmal C spawn、locomotion、sensor/TF/odometry、`cmd_vel`、Episode
reset、安全门控或完整 MVP E2E。Env 因而仍保持 `STARTING`，不能提前宣称
`READY`。

## 7. 运行后风扇或 GPU 负载升高

Isaac/Kit 初始化 physics、renderer 和 shader cache 时出现明显 GPU/CPU 负载是
正常现象。先检查是否仍有项目容器运行：

```bash
docker compose \
  --env-file deployment/env/versions.env \
  --env-file deployment/env/.env \
  -f deployment/compose/compose.isaac.yaml ps
nvidia-smi
```

本地 GUI 推荐使用前台启动脚本：

```bash
make isaac-gui
```

它不会修改 `.env` 中默认的 headless 模式；脚本会临时授权容器 root 用户访问
当前 X11 display，在 Ctrl-C 或异常退出后清理 Compose stack，并只撤销本次新增的
X11 ACL。首次启动可能需要数分钟编译 RTX shader；若桌面弹出 Wait/Force Quit，
且日志仍在更新 `Waiting for RtPso async group async compilation`，应选择 Wait。
缓存保存在命名 volume 中，后续启动会复用。手动通过 `make isaac-up` 启动的后台
服务仍需要显式停止：

```bash
make isaac-down
```

`make isaac-smoke` 自带退出清理；即使验证失败，也会尽力保存日志并停止本次
Compose stack。
