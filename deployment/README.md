# Deployment and development environments

`deployment/` is the authority for container images, Compose services, runtime
mounts, and version pins.

## Image boundary

RoboHarness keeps development and execution concerns in separate images:

| Image | Purpose | Source mount | Build tools |
| --- | --- | --- | --- |
| `roboharness-dev` | edit, build, lint, and test the monorepo | yes | Colcon, compiler, CMake, Ruff |
| `roboharness-mock-runtime` | execute the installed CPU mock stack | no | no repository lint/dev layer |
| `roboharness-isaac-env` | run the Isaac backend and native ROS 2 Bridge | no | no repository lint/dev layer |

The mock runtime image is built with a multi-stage Dockerfile. Its builder
stage compiles the required Colcon packages, while the final stage copies only
the merged install tree onto the pinned ROS 2 base. The ROS base may itself
contain upstream command-line utilities; the runtime adds no repository source,
Ruff, build cache, or builder filesystem. The same immutable image is used by
three independently supervised containers; sharing an image does not merge
their process or service boundaries.

## CPU development container

The supported development path is an Ubuntu 22.04 / ROS 2 Humble CPU
container. It is a temporary tool environment and is not a fourth RoboHarness
runtime service.

From the repository root:

```bash
make dev-image
make dev-shell
```

The repository is bind-mounted at `/workspace/roboharness`. The image is built
with the host UID and GID so generated files remain owned by the developer.
The container entrypoint sources only `/opt/ros/humble`; it deliberately does
not source an existing RoboHarness overlay before rebuilding. Source
`.build/colcon/install/setup.bash` explicitly when running built nodes.

The ROS base is the Docker Official Image published through its official AWS
ECR Public distribution channel. `deployment/env/versions.env` pins the
validated manifest digest so local and CI builds use identical ROS base
content. It also records the host and container toolchain versions exercised by
PR 01.

## CPU mock runtime

Run the complete reference stack and validate its artifacts with:

```bash
make mock-e2e
```

Compose starts exactly three containers on one private bridge network:

- `env` publishes deterministic clock/odometry and implements Environment reset;
- `agent` consumes PointNav tasks and publishes velocity commands;
- `experiment` runs bringup, coordination, evaluation, and result recording.

The harness waits on observable ROS graph and result commit conditions rather
than assuming startup durations. It also verifies that all three containers
stay alive without restarts and that the final runtime contains the installed
overlay without a source workspace or repository lint tooling. Results,
container snapshots, ROS graph snapshots, and Compose logs are retained under
`.build/mock-e2e/`; the stack is always removed on exit.

This CPU image is a reproducible protocol and orchestration reference, not an
Isaac production image.

## Isaac backend skeleton

PR 13 pins the Linux x86_64 Isaac Sim image to both version and manifest:

```text
nvcr.io/nvidia/isaac-sim:4.5.0
sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7
```

The env image adds only the installed `rh_interfaces` overlay and the
`simulators/isaac` application files. It contains no source workspace, Isaac
Lab, ANYmal C binding, policy training tools, Agent, Task, Evaluator, or
Experiment implementation. The `rh.isaac` extension enables the native
`isaacsim.ros2.bridge`, creates the simulation-clock Action Graph, and publishes
the platform Env status as `STARTING` or `ERROR`. It deliberately cannot claim
`READY` before PR 14 and PR 16 provide the robot binding and full Env contract.

Create the local consent/configuration file and explicitly accept NVIDIA's EULA:

```bash
cp deployment/env/.env.example deployment/env/.env
# Edit deployment/env/.env and set ACCEPT_EULA=Y after reviewing the EULA.
make isaac-config
make isaac-image
make isaac-up
```

On a local Linux X11 session, run the foreground GUI workflow without changing
the default headless value in `.env`:

```bash
make isaac-gui
```

The GUI helper validates `DISPLAY`, temporarily grants only the container root
user local X access, and cleans up both Compose and the added X access on exit.

`compose.isaac.yaml` uses host networking and a shared host IPC namespace for
the Linux-only PR 13 Fast DDS smoke, passes through all NVIDIA GPUs, and
persists shader/content caches in named volumes. Sharing IPC is required for
Fast DDS shared-memory user data; discovery alone can work across isolated IPC
namespaces while `/clock` delivery fails. `bridge-observer` is a
validation-profile helper, not a fourth runtime service. Stop the stack with
`make isaac-down`.

The bounded manual validation command is:

```bash
make isaac-smoke
```

It checks the host driver and Docker runtime, builds the pinned image, starts an
external ROS 2 Humble observer, receives one `/clock` message, checks the Env
status topic and container stability, and writes evidence under
`.build/isaac-smoke/`. See the
[PR 13 validation guide](../docs/guides/isaac-pr13-validation.md) for host
requirements, GUI launch, evidence contents, and limitations. Developers
preparing a new machine should first follow the
[NVIDIA Container Toolkit host setup guide](../docs/guides/nvidia-container-toolkit-host-setup.md).

The complete separation between host configuration, repository pins, local
consent, and implementation changes is recorded in the
[PR 13 development environment notes](../docs/guides/isaac-pr13-development-environment.md).
The 2026-08-24 smoke passed on Ubuntu 22.04.5/kernel 6.8 with driver
`580.173.02`, NVIDIA Container Toolkit `1.20.0`, Docker Engine `29.7.2`, and
Compose `5.5.0`. These are validation evidence, not blanket minimum versions
for every host.

Isaac Sim 4.5.0, Ubuntu 22.04, and ROS 2 Humble are the selected runtime
baseline. The MVP later uses the ANYmal C locomotion policy bundled with Isaac
Sim, so Isaac Lab is not installed in the runtime image. Policy training or
export tooling will be selected and pinned separately if required.
