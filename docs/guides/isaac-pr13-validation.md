# PR 13 Isaac Backend and Native ROS 2 Bridge Validation

This guide validates the bounded PR 13 skeleton. Passing it proves that the
pinned Isaac Sim 4.5 container can start the RoboHarness Kit application on a
specific host and that an external ROS 2 Humble container can discover and
receive the native Bridge simulation clock. It does not validate ANYmal C,
sensors, locomotion, reset, command gating, or an Episode.

## Fixed software boundary

- Host OS: Ubuntu 22.04 x86_64
- ROS: ROS 2 Humble
- Isaac Sim: `4.5.0`
- Isaac image manifest:
  `sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7`
- Native Bridge extension: `isaacsim.ros2.bridge`
- RMW for this smoke: `rmw_fastrtps_cpp`
- Isaac Lab: not installed

NVIDIA documents Linux driver `535.129.03` as the 4.5 baseline and recommends
at least `535.216.01` with Ubuntu 22.04.5 kernel 6.8. Record the actual tested
driver; do not infer compatibility from the package version alone.

The repository has a passing reference snapshot from 2026-08-24 using Ubuntu
22.04.5, kernel `6.8.0-138-generic`, NVIDIA driver `580.173.02`, Container
Toolkit `1.20.0`, Docker Engine `29.7.2`, and Compose `5.5.0`. Driver 580 is a
known-good result for that host, not the project minimum.

## Host preflight

The host must have an RTX-capable NVIDIA GPU, a functioning driver, Docker
Engine, Docker Compose v2, and NVIDIA Container Toolkit. All of these commands
must succeed before building the large image:

Install or repair the host runtime with the
[NVIDIA Container Toolkit host setup guide](nvidia-container-toolkit-host-setup.md)
before running this PR-specific validation.

```bash
nvidia-smi
nvidia-container-cli --version
docker version
docker compose version
docker run --rm --gpus all ubuntu nvidia-smi
```

The last command may download a small image. A missing `nvidia-container-cli`
means NVIDIA Container Toolkit is not installed. A failed `nvidia-smi`, an
unreachable Docker socket, or a failed container GPU probe is a host/runtime
failure, not evidence that the RoboHarness extension is broken.

## Consent and static configuration

The repository does not accept NVIDIA terms on behalf of the operator:

```bash
cp deployment/env/.env.example deployment/env/.env
```

Review NVIDIA's Omniverse EULA, then set `ACCEPT_EULA=Y`. Keep
`PRIVACY_CONSENT=N` unless the operator explicitly opts in. The local `.env`
file is ignored by Git.

Validate Compose interpolation without starting a container:

```bash
make isaac-config
```

## Headless GPU and Bridge smoke

Run:

```bash
make isaac-smoke
```

The harness performs observable checks rather than assuming a fixed startup
delay:

1. capture GPU, Docker, Compose, resolved configuration, and image metadata;
2. build the env image from the digest-pinned Isaac Sim base;
3. start `env` and the validation-only ROS 2 observer with host networking and
   a shared host IPC namespace;
4. wait for an external `ros2 topic echo /clock --once` to succeed;
5. verify `/clock` has type `rosgraph_msgs/msg/Clock`;
6. verify `/roboharness/env/status` is discoverable with the platform type;
7. confirm neither validation container restarted; and
8. require the external observer to report at least one `/clock` publisher.

Evidence is retained under `.build/isaac-smoke/<UTC token>/` even when the run
fails. A passing directory includes `result.txt`, `nvidia-smi.txt`, resolved
Compose, image metadata, node/topic snapshots, one clock message, container
snapshots, and Isaac/Compose logs. Attach this directory to the PR GPU evidence.

Both containers use `ipc: host` because Fast DDS can select shared-memory
transport for colocated participants. With separate IPC namespaces, DDS topic
discovery can still succeed while user data such as `/clock` never reaches the
observer. Seeing a publisher is therefore not equivalent to receiving data.

## Local GUI launch

GUI is a manual supplement to the headless acceptance test:

```bash
make isaac-gui
```

The launcher requires a real local `DISPLAY` and X11 socket, checks the host GPU
and Docker runtime, temporarily grants the container root user X access, builds
and starts the `env` service in the foreground, and restores the X access rule
after Ctrl-C. It does not rewrite the default `RH_ISAAC_MODE=headless` in the
developer's `.env`. Remote GUI/WebRTC streaming is not configured by PR 13.

The first GUI run can spend several minutes compiling RTX pipeline shaders. A
desktop "Wait or Force Quit" prompt during this phase does not by itself mean
Kit crashed: choose **Wait** while the log continues to report
`Waiting for RtPso async group async compilation`. The named Omniverse cache
volume is preserved, so later starts normally reuse the compiled data. Treat a
CUDA/Vulkan error, container exit, or a non-progressing warm-up beyond the host
timeout as a separate failure; do not delete the cache during diagnosis.

## Expected PR 13 state semantics

`/roboharness/env/status` remains `STARTING` with detail indicating that the
native clock smoke is active. This is intentional. The extension publishes
`ERROR` with a restart-required flag if initialization fails, but it cannot
publish `READY` until the stage, ANYmal C binding, required sensors/interfaces,
reset behavior, and command safety gate are implemented and validated.

## Acceptance record

Record the evidence directory and actual values in the PR description:

```text
host_os=
kernel=
gpu=
driver=
docker_engine=
docker_compose=
isaac_image_digest=
headless_clock_smoke=PASS|FAIL
gui_launch=PASS|FAIL|NOT_RUN
evidence_directory=
known_limitations=
```

Reference result:

```text
headless_clock_smoke=PASS
gui_launch=PASS (window opened; first-run RtPso warm-up observed)
driver=580.173.02
toolkit=1.20.0
evidence_directory=.build/isaac-smoke/20260824T083123Z-112676
known_limitations=PR13 clock/status skeleton only; Env remains STARTING
```

The evidence directory is local generated data and is intentionally ignored by
Git. Record the values and result in the PR description; do not commit the
large image metadata and runtime logs.
