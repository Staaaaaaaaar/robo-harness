# Deployment and development environments

`deployment/` is the authority for container images, Compose services, runtime
mounts, and version pins.

## CPU development container

The only supported PR 01 development path is an Ubuntu 22.04 / ROS 2 Humble CPU
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

The future production deployment contains exactly `env`, `agent`, and
`experiment`. Their Dockerfiles and Compose definitions are intentionally not
stubbed in PR 01. Isaac/GPU versions and development overrides are added after
validation in PR 13.
