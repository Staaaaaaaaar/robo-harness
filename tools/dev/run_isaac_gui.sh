#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSIONS_FILE="${ROOT_DIR}/deployment/env/versions.env"
ISAAC_ENV_FILE="${RH_ISAAC_ENV_FILE:-${ROOT_DIR}/deployment/env/.env}"
HOST_DISPLAY="${DISPLAY:-}"
XHOST_ENTRY="SI:localuser:root"
x_access_added=false

fail() {
    echo "Isaac GUI launch failed: $*" >&2
    exit 1
}

[[ -n "${HOST_DISPLAY}" ]] \
    || fail "DISPLAY is empty; run this command from a local graphical session"
[[ -f "${ISAAC_ENV_FILE}" ]] \
    || fail "missing ${ISAAC_ENV_FILE}; copy deployment/env/.env.example first"

display_number="${HOST_DISPLAY##*:}"
display_number="${display_number%%.*}"
[[ -S "/tmp/.X11-unix/X${display_number}" ]] \
    || fail "the local X11 socket for DISPLAY=${HOST_DISPLAY} is unavailable"

for command_name in docker nvidia-container-cli nvidia-smi xhost; do
    command -v "${command_name}" >/dev/null \
        || fail "required command is unavailable: ${command_name}"
done

set -a
source "${VERSIONS_FILE}"
source "${ISAAC_ENV_FILE}"
set +a

[[ "${ACCEPT_EULA:-N}" == "Y" ]] \
    || fail "set ACCEPT_EULA=Y only after accepting the NVIDIA Omniverse EULA"

# The GUI launcher is intentionally an ephemeral override. It does not rewrite
# the developer's default headless setting in deployment/env/.env.
export DISPLAY="${HOST_DISPLAY}"
export RH_ISAAC_MODE=gui

COMPOSE=(
    docker compose
    --env-file "${VERSIONS_FILE}"
    --env-file "${ISAAC_ENV_FILE}"
    --project-name roboharness-isaac
    -f "${ROOT_DIR}/deployment/compose/compose.isaac.yaml"
)

cleanup() {
    local exit_code=$?
    trap - EXIT
    "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
    if [[ "${x_access_added}" == true ]]; then
        xhost -si:localuser:root >/dev/null 2>&1 || true
    fi
    exit "${exit_code}"
}

docker compose version >/dev/null
docker info >/dev/null
nvidia-smi >/dev/null
nvidia-container-cli --version >/dev/null
"${COMPOSE[@]}" config --quiet

if [[ -n "$("${COMPOSE[@]}" ps --quiet)" ]]; then
    fail "the roboharness-isaac stack is already running; stop it with make isaac-down"
fi

# Preserve a pre-existing ACL entry. Revoke only the access added by this run.
trap cleanup EXIT
if ! xhost | grep -Fq "${XHOST_ENTRY}"; then
    xhost +si:localuser:root >/dev/null
    x_access_added=true
fi

echo "Starting Isaac Sim GUI on DISPLAY=${DISPLAY}. Press Ctrl-C to stop and clean up."
echo "The first RTX shader warm-up may take several minutes; choose Wait, not Force Quit."
"${COMPOSE[@]}" up --build env
