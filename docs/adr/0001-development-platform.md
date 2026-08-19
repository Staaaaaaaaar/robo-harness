# ADR 0001: Development platform baseline

- Status: Accepted
- Date: 2026-08-17
- Roadmap: PR 01 — Repository Foundation

## Context

RoboHarness needs one reproducible baseline before ROS interfaces, mock
components, and Isaac integration can be developed independently. Supporting
both native and container-first workflows would create two installation and
validation paths before the platform has runtime code.

## Decision

The supported development baseline is:

- Ubuntu 22.04 LTS;
- ROS 2 Humble installed from the official ROS packages;
- Python 3.10 supplied by Ubuntu 22.04;
- a CPU development container as the only documented development path;
- Colcon and ament for ROS package discovery, build, and tests;
- Docker Compose v2 and a root Makefile as thin repository-level entry points.
- the Docker Official ROS image from AWS ECR Public, pinned by manifest digest.
- Isaac Sim 4.5.0 for the GPU environment backend;
- ANYmal C as the first reference quadruped, using the official Isaac Sim
  locomotion-policy example as the initial simulator-only locomotion backend.

The host requires Git, Docker Engine, Docker Compose v2, and Make. It does not
require a native ROS installation. ROS and system dependencies are installed in
the development image through apt and rosdep; Python repository tools are pinned
inside that image and must not alter host Python.

The CPU development container is not part of the RoboHarness runtime topology.
Production remains exactly three services: `env`, `agent`, and `experiment`.
Isaac development will reuse the future `env` image with a development Compose
override rather than create a second, divergent GPU image.

The Isaac Sim and reference-robot versions are selected now to keep the Ubuntu
22.04 / ROS 2 Humble / Python 3.10 baseline intact. PR 13 still validates the
exact production image digest, NVIDIA driver requirements, GPU runtime, and
native ROS 2 Bridge compatibility. The initial ANYmal C policy is bundled with
Isaac Sim and is a simulator reference rather than a claim of real-robot
deployment capability. Isaac Lab is not an MVP runtime dependency: the project
does not train or export policies, and a future need for that tooling requires a
separate version and dependency decision.

References:

- [ROS 2 Humble platform support](https://www.ros.org/reps/rep-2000.html)
- [Isaac Sim 4.5 ROS 2 support](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/installation/install_ros.html)
- [Isaac Sim 4.5 policy examples](https://docs.isaacsim.omniverse.nvidia.com/4.5.0/robot_simulation/ext_isaacsim_robot_policy_example.html)
- [Docker Official Images on Amazon ECR Public](https://www.docker.com/blog/news-from-aws-reinvent-docker-official-images-on-amazon-ecr-public/)

## Consequences

- Local and CI checks execute in the same toolchain.
- Developers do not need to maintain ROS or Python dependencies on the host.
- Initial image download and build take longer than a native setup.
- GUI, GPU, device, and DDS cross-container concerns are deferred to the PR that
  introduces the relevant runtime integration.
- Isaac-related runtime code and images must pin `4.5.0`; Isaac Lab must not be
  added transitively through the policy example. Introducing policy training or
  export tooling requires an explicit scope and version decision.
- A baseline change requires a superseding ADR and corresponding CI/container
  update.
