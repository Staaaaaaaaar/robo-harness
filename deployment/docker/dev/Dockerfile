ARG ROS_BASE_IMAGE=public.ecr.aws/docker/library/ros:humble-ros-base-jammy
FROM ${ROS_BASE_IMAGE}

ARG USER_UID=1000
ARG USER_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        ca-certificates \
        ccache \
        cmake \
        git \
        make \
        python3-colcon-common-extensions \
        python3-pip \
        python3-rosdep \
        python3-yaml \
        ros-dev-tools \
    && rm -rf /var/lib/apt/lists/*

COPY tools/dev/requirements.txt /tmp/roboharness-dev-requirements.txt
RUN python3 -m pip install --no-cache-dir \
        -r /tmp/roboharness-dev-requirements.txt \
    && rm /tmp/roboharness-dev-requirements.txt

RUN if getent group "${USER_GID}" >/dev/null; then \
        group_name="$(getent group "${USER_GID}" | cut -d: -f1)"; \
    else \
        groupadd --gid "${USER_GID}" developer; \
        group_name=developer; \
    fi \
    && useradd --uid "${USER_UID}" --gid "${group_name}" \
        --create-home --shell /bin/bash developer \
    && install -d -o "${USER_UID}" -g "${USER_GID}" /home/developer/.ccache \
    && if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then \
        rosdep init; \
    fi

COPY deployment/docker/dev/entrypoint.sh /usr/local/bin/roboharness-dev-entrypoint
RUN chmod 0755 /usr/local/bin/roboharness-dev-entrypoint

USER developer
WORKDIR /workspace/roboharness

ENTRYPOINT ["/usr/local/bin/roboharness-dev-entrypoint"]
CMD ["bash"]
