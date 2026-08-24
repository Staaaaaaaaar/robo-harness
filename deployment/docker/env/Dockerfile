ARG ROS_BASE_IMAGE=public.ecr.aws/docker/library/ros:humble-ros-base-jammy
ARG ISAAC_SIM_IMAGE=nvcr.io/nvidia/isaac-sim:4.5.0

FROM ${ROS_BASE_IMAGE} AS ros-builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        cmake \
        python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/roboharness
COPY packages/rh_interfaces packages/rh_interfaces

RUN source /opt/ros/humble/setup.bash \
    && colcon build \
        --merge-install \
        --install-base /opt/roboharness \
        --base-paths packages \
        --packages-select rh_interfaces

FROM ${ISAAC_SIM_IMAGE} AS isaac-env

ARG ISAAC_SIM_IMAGE

LABEL org.opencontainers.image.title="RoboHarness Isaac environment" \
      org.opencontainers.image.description="Isaac Sim 4.5 backend and native ROS 2 Bridge" \
      org.opencontainers.image.version="4.5.0" \
      org.opencontainers.image.base.name="${ISAAC_SIM_IMAGE}"

USER root

COPY --from=ros-builder /opt/roboharness /opt/roboharness
COPY simulators/isaac /opt/roboharness/simulators/isaac
COPY deployment/docker/env/entrypoint.sh /usr/local/bin/roboharness-isaac-entrypoint

RUN chmod 0755 \
        /usr/local/bin/roboharness-isaac-entrypoint \
        /opt/roboharness/simulators/isaac/scripts/launch.sh

ENV RH_ISAAC_ROOT=/isaac-sim \
    RH_ISAAC_APPS=/isaac-sim/apps \
    RH_ISAAC_BASE_APP=/isaac-sim/apps/isaacsim.exp.base.kit \
    RH_ISAAC_APP=/opt/roboharness/simulators/isaac/apps/rh.kit \
    RH_ISAAC_EXTENSIONS=/opt/roboharness/simulators/isaac/extensions \
    RH_ROS_PYTHON_PATH=/opt/roboharness/local/lib/python3.10/dist-packages \
    AMENT_PREFIX_PATH=/opt/roboharness \
    PYTHONPATH=/opt/roboharness/local/lib/python3.10/dist-packages \
    LD_LIBRARY_PATH=/opt/roboharness/lib

WORKDIR /isaac-sim
ENTRYPOINT ["/usr/local/bin/roboharness-isaac-entrypoint"]
CMD ["headless"]
