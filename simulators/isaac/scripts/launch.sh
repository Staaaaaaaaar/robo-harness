#!/usr/bin/env bash
set -eo pipefail

ISAAC_ROOT="${RH_ISAAC_ROOT:-/isaac-sim}"
ISAAC_APPS_PATH="${RH_ISAAC_APPS:-${ISAAC_ROOT}/apps}"
BASE_APP="${RH_ISAAC_BASE_APP:-${ISAAC_APPS_PATH}/isaacsim.exp.base.kit}"
APP_PATH="${RH_ISAAC_APP:-/opt/roboharness/simulators/isaac/apps/rh.kit}"
EXTENSIONS_PATH="${RH_ISAAC_EXTENSIONS:-/opt/roboharness/simulators/isaac/extensions}"
ROS_DISTRO="${ROS_DISTRO:-humble}"
BRIDGE_ROS_LIB="${ISAAC_ROOT}/exts/isaacsim.ros2.bridge/${ROS_DISTRO}/lib"
MODE="${1:-headless}"
shift || true

if [[ -f "${ISAAC_ROOT}/setup_python_env.sh" ]]; then
    # The NVIDIA launcher uses this environment for Kit's bundled Python and
    # native ROS 2 Bridge libraries.
    source "${ISAAC_ROOT}/setup_python_env.sh"
fi

export AMENT_PREFIX_PATH="/opt/roboharness${AMENT_PREFIX_PATH:+:${AMENT_PREFIX_PATH}}"
export PYTHONPATH="/opt/roboharness/local/lib/python3.10/dist-packages${PYTHONPATH:+:${PYTHONPATH}}"
export ROS_DISTRO
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export LD_LIBRARY_PATH="${BRIDGE_ROS_LIB}:/opt/roboharness/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

KIT=(
    "${ISAAC_ROOT}/kit/kit"
    "${BASE_APP}"
    "--merge-config=${APP_PATH}"
    --ext-folder "${ISAAC_APPS_PATH}"
    --ext-folder "${EXTENSIONS_PATH}"
    --enable isaacsim.ros2.bridge
    --enable rh.isaac
)

if [[ "${EUID}" -eq 0 ]]; then
    KIT+=(--allow-root)
fi

case "${MODE}" in
    headless)
        KIT+=(--no-window)
        ;;
    gui)
        if [[ -z "${DISPLAY:-}" ]]; then
            echo "GUI mode requires DISPLAY and the X11 socket." >&2
            exit 64
        fi
        ;;
    *)
        echo "Unsupported Isaac launch mode: ${MODE}; expected headless or gui." >&2
        exit 64
        ;;
esac

exec "${KIT[@]}" "$@"
