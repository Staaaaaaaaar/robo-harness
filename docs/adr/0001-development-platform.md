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

The host requires Git, Docker Engine, Docker Compose v2, and Make. It does not
require a native ROS installation. ROS and system dependencies are installed in
the development image through apt and rosdep; Python repository tools are pinned
inside that image and must not alter host Python.

The CPU development container is not part of the RoboHarness runtime topology.
Production remains exactly three services: `env`, `agent`, and `experiment`.
Isaac development will reuse the future `env` image with a development Compose
override rather than create a second, divergent GPU image.

The exact Isaac Sim version, NVIDIA driver requirements, production image tags
and digests, and ROS bridge compatibility remain unverified until PR 13. Humble
is selected now because Ubuntu 22.04 is its native Tier 1 platform and it is a
recommended Isaac Sim ROS 2 integration target.

References:

- [ROS 2 Humble platform support](https://www.ros.org/reps/rep-2000.html)
- [Isaac Sim ROS 2 support](https://docs.isaacsim.omniverse.nvidia.com/latest/ros2_tutorials/ros2_landing_page.html)
- [Docker Official Images on Amazon ECR Public](https://www.docker.com/blog/news-from-aws-reinvent-docker-official-images-on-amazon-ecr-public/)

## Consequences

- Local and CI checks execute in the same toolchain.
- Developers do not need to maintain ROS or Python dependencies on the host.
- Initial image download and build take longer than a native setup.
- GUI, GPU, device, and DDS cross-container concerns are deferred to the PR that
  introduces the relevant runtime integration.
- A baseline change requires a superseding ADR and corresponding CI/container
  update.
