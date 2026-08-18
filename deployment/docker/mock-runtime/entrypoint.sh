#!/usr/bin/env bash
set -eo pipefail

source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
source /opt/roboharness/setup.bash

set -u

exec "$@"
