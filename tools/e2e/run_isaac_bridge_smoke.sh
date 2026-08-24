#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSIONS_FILE="${ROOT_DIR}/deployment/env/versions.env"
ISAAC_ENV_FILE="${RH_ISAAC_ENV_FILE:-${ROOT_DIR}/deployment/env/.env}"
RUN_TOKEN="${RH_ISAAC_RUN_TOKEN:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RUN_DIR="${RH_ISAAC_RESULTS_ROOT:-${ROOT_DIR}/.build/isaac-smoke}/${RUN_TOKEN}"
DEADLINE_SECONDS="${RH_ISAAC_TIMEOUT_S:-600}"

fail() {
    echo "Isaac Bridge smoke failed: $*" >&2
    return 1
}

[[ -f "${ISAAC_ENV_FILE}" ]] \
    || fail "missing ${ISAAC_ENV_FILE}; copy deployment/env/.env.example first"

set -a
source "${VERSIONS_FILE}"
source "${ISAAC_ENV_FILE}"
set +a

[[ "${ACCEPT_EULA:-N}" == "Y" ]] \
    || fail "set ACCEPT_EULA=Y only after accepting the NVIDIA Omniverse EULA"
[[ "${RH_ISAAC_MODE:-headless}" == "headless" ]] \
    || fail "the automated smoke requires RH_ISAAC_MODE=headless"

for command_name in docker nvidia-container-cli nvidia-smi timeout; do
    command -v "${command_name}" >/dev/null \
        || fail "required command is unavailable: ${command_name}"
done

mkdir -p "${RUN_DIR}"

COMPOSE=(
    docker compose
    --env-file "${VERSIONS_FILE}"
    --env-file "${ISAAC_ENV_FILE}"
    --project-name roboharness-isaac
    --profile validation
    -f "${ROOT_DIR}/deployment/compose/compose.isaac.yaml"
)

observer_exec() {
    "${COMPOSE[@]}" exec -T bridge-observer bash -lc \
        'source "/opt/ros/${ROS_DISTRO}/setup.bash"; exec "$@"' bash "$@"
}

cleanup() {
    local exit_code=$?
    "${COMPOSE[@]}" logs --no-color >"${RUN_DIR}/compose.log" 2>&1 || true
    "${COMPOSE[@]}" ps --all >"${RUN_DIR}/compose-ps.txt" 2>&1 || true
    "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
    return "${exit_code}"
}
trap cleanup EXIT

nvidia-smi >"${RUN_DIR}/nvidia-smi.txt"
nvidia-container-cli --version >"${RUN_DIR}/nvidia-container-toolkit-version.txt"
docker version >"${RUN_DIR}/docker-version.txt"
docker compose version >"${RUN_DIR}/compose-version.txt"
"${COMPOSE[@]}" config >"${RUN_DIR}/compose-resolved.yaml"

echo "Building the pinned Isaac Sim 4.5 environment image..."
"${COMPOSE[@]}" build env
docker image inspect "${RH_ISAAC_ENV_IMAGE}" >"${RUN_DIR}/env-image.json"

echo "Starting Isaac env and the external ROS 2 observer..."
"${COMPOSE[@]}" up --detach env bridge-observer

env_id="$("${COMPOSE[@]}" ps -q env)"
observer_id="$("${COMPOSE[@]}" ps -q bridge-observer)"
[[ -n "${env_id}" && -n "${observer_id}" ]] \
    || fail "Compose did not create both validation containers"
docker inspect --format '{{.Id}} {{.State.Pid}} {{.RestartCount}}' \
    "${env_id}" "${observer_id}" >"${RUN_DIR}/containers.before"

deadline=$((SECONDS + DEADLINE_SECONDS))
clock_seen=false
while ((SECONDS < deadline)); do
    if [[ "$(docker inspect --format '{{.State.Running}}' "${env_id}")" != true ]]; then
        fail "Isaac env exited before the Bridge became observable"
    fi
    if observer_exec timeout 10 ros2 topic echo /clock --once \
        >"${RUN_DIR}/clock.txt" 2>"${RUN_DIR}/clock.stderr"; then
        clock_seen=true
        break
    fi
    sleep 2
done
[[ "${clock_seen}" == true ]] || fail "/clock was not received before the deadline"

observer_exec ros2 node list \
    >"${RUN_DIR}/ros-nodes.txt"
observer_exec ros2 topic list -t \
    >"${RUN_DIR}/ros-topics.txt"
observer_exec ros2 topic info /clock --verbose \
    >"${RUN_DIR}/clock-info.txt"

grep -Fq '/clock [rosgraph_msgs/msg/Clock]' "${RUN_DIR}/ros-topics.txt" \
    || fail "external observer reported an unexpected /clock type"
grep -Fq '/roboharness/env/status [rh_interfaces/msg/ComponentStatus]' \
    "${RUN_DIR}/ros-topics.txt" \
    || fail "Isaac extension status topic is absent from the external ROS graph"

docker inspect --format '{{.Id}} {{.State.Pid}} {{.RestartCount}}' \
    "${env_id}" "${observer_id}" >"${RUN_DIR}/containers.after"
cmp --silent "${RUN_DIR}/containers.before" "${RUN_DIR}/containers.after" \
    || fail "a validation container restarted during the smoke"

"${COMPOSE[@]}" logs --no-color env >"${RUN_DIR}/env.log"
# Kit persists carb Info records separately and does not reliably mirror them
# to Compose stdout. The externally received clock plus its publisher metadata
# are the runtime contract; do not make the smoke depend on log routing.
grep -Eq 'Publisher count: [1-9][0-9]*' "${RUN_DIR}/clock-info.txt" \
    || fail "external observer did not find a /clock publisher"

cat >"${RUN_DIR}/result.txt" <<EOF
result=PASS
isaac_sim_version=${RH_ISAAC_SIM_VERSION}
isaac_sim_image=${RH_ISAAC_SIM_IMAGE}
validated_driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)
ros_domain_id=${RH_ISAAC_ROS_DOMAIN_ID}
EOF

echo "Isaac Bridge smoke passed. Evidence: ${RUN_DIR}"
