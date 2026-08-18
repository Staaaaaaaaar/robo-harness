ARG ROS_BASE_IMAGE=public.ecr.aws/docker/library/ros:humble-ros-base-jammy

FROM ${ROS_BASE_IMAGE} AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        cmake \
        python3-colcon-common-extensions \
        python3-yaml \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/roboharness

COPY packages packages
COPY tasks tasks
COPY evaluators evaluators
COPY tests/fixtures tests/fixtures

RUN source /opt/ros/humble/setup.bash \
    && colcon build \
        --merge-install \
        --install-base /opt/roboharness \
        --base-paths packages tasks evaluators tests/fixtures \
        --packages-up-to rh_bringup rh_mock_agent rh_mock_env

FROM ${ROS_BASE_IMAGE} AS mock-runtime

ARG USER_UID=1000
ARG USER_GID=1000

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        python3-yaml \
    && rm -rf /var/lib/apt/lists/* \
    && if getent group "${USER_GID}" >/dev/null; then \
        group_name="$(getent group "${USER_GID}" | cut -d: -f1)"; \
    else \
        groupadd --gid "${USER_GID}" runtime; \
        group_name=runtime; \
    fi \
    && if ! getent passwd "${USER_UID}" >/dev/null; then \
        useradd --uid "${USER_UID}" --gid "${group_name}" \
            --no-create-home --home-dir /home/runtime --shell /bin/bash runtime; \
    fi \
    && install -d -o "${USER_UID}" -g "${USER_GID}" /home/runtime /results

COPY --from=builder /opt/roboharness /opt/roboharness
COPY deployment/docker/mock-runtime/entrypoint.sh \
    /usr/local/bin/roboharness-runtime-entrypoint

RUN chmod 0755 /usr/local/bin/roboharness-runtime-entrypoint

ENV HOME=/home/runtime
USER ${USER_UID}:${USER_GID}
WORKDIR /home/runtime

ENTRYPOINT ["/usr/local/bin/roboharness-runtime-entrypoint"]
CMD ["ros2", "pkg", "list"]
