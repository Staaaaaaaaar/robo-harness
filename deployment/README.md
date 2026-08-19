# Deployment and development environments

`deployment/` is the authority for container images, Compose services, runtime
mounts, and version pins.

## Image boundary

RoboHarness keeps development and execution concerns in separate images:

| Image | Purpose | Source mount | Build tools |
| --- | --- | --- | --- |
| `roboharness-dev` | edit, build, lint, and test the monorepo | yes | Colcon, compiler, CMake, Ruff |
| `roboharness-mock-runtime` | execute the installed CPU mock stack | no | no repository lint/dev layer |

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
Isaac production image. Isaac Sim 4.5.0, Ubuntu 22.04, and ROS 2 Humble are the
selected runtime baseline; the exact GPU image digest and host-driver validation
remain the scope of PR 13. The MVP uses the ANYmal C locomotion policy bundled
with Isaac Sim, so Isaac Lab is not installed in the runtime image. Policy
training or export tooling will be selected and pinned separately if required.
