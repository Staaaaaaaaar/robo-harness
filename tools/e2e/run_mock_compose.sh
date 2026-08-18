#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_TOKEN="${RH_E2E_RUN_TOKEN:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
PROJECT_NAME="rhmock-${RUN_TOKEN,,}"
PROJECT_NAME="${PROJECT_NAME//[^a-z0-9_-]/-}"
RUN_DIR="${RH_E2E_RESULTS_ROOT:-${ROOT_DIR}/.build/mock-e2e}/${RUN_TOKEN}"
EXPERIMENT_ID="${RH_EXPERIMENT_ID:-mock-compose-${RUN_TOKEN}}"
RESULT_DIR="${RUN_DIR}/${EXPERIMENT_ID}"
DEADLINE_SECONDS="${RH_E2E_TIMEOUT_S:-120}"

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
export RH_RESULTS_DIR="${RUN_DIR}"
export RH_EXPERIMENT_ID="${EXPERIMENT_ID}"

COMPOSE=(
    docker compose
    --env-file "${ROOT_DIR}/deployment/env/versions.env"
    --project-name "${PROJECT_NAME}"
    -f "${ROOT_DIR}/deployment/compose/compose.mock.yaml"
)
SERVICES=(env agent experiment)
RUNTIME_ENTRYPOINT=/usr/local/bin/roboharness-runtime-entrypoint

mkdir -p "${RUN_DIR}"

cleanup() {
    local exit_code=$?
    "${COMPOSE[@]}" logs --no-color >"${RUN_DIR}/compose.log" 2>&1 || true
    "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    return "${exit_code}"
}
trap cleanup EXIT

fail() {
    echo "Mock Compose E2E failed: $*" >&2
    return 1
}

contains_line() {
    local content=$1
    local expected=$2
    grep -Fqx -- "${expected}" <<<"${content}"
}

container_snapshot() {
    local service container_id
    for service in "${SERVICES[@]}"; do
        container_id="$("${COMPOSE[@]}" ps -q "${service}")"
        [[ -n "${container_id}" ]] || fail "${service} container is missing"
        docker inspect --format '{{.Id}} {{.State.Pid}} {{.RestartCount}} {{.State.Status}}' \
            "${container_id}"
    done
}

echo "Building the minimal CPU mock runtime image..."
"${COMPOSE[@]}" build experiment
echo "Starting env, agent, and experiment containers..."
"${COMPOSE[@]}" up --detach --no-build

deadline=$((SECONDS + DEADLINE_SECONDS))
graph_ready=false
while ((SECONDS < deadline)); do
    for service in "${SERVICES[@]}"; do
        container_id="$("${COMPOSE[@]}" ps -q "${service}")"
        if [[ -z "${container_id}" ]] \
            || [[ "$(docker inspect --format '{{.State.Running}}' "${container_id}")" != true ]]; then
            fail "${service} container exited before the ROS graph became ready"
        fi
    done
    nodes="$("${COMPOSE[@]}" exec -T experiment \
        "${RUNTIME_ENTRYPOINT}" ros2 node list 2>/dev/null || true)"
    topics="$("${COMPOSE[@]}" exec -T experiment \
        "${RUNTIME_ENTRYPOINT}" ros2 topic list 2>/dev/null || true)"
    services="$("${COMPOSE[@]}" exec -T experiment \
        "${RUNTIME_ENTRYPOINT}" ros2 service list 2>/dev/null || true)"
    if contains_line "${nodes}" "/rh_mock_env" \
        && contains_line "${nodes}" "/rh_mock_agent" \
        && contains_line "${nodes}" "/rh_experiment_orchestrator" \
        && contains_line "${topics}" "/clock" \
        && contains_line "${topics}" "/robot/odom" \
        && contains_line "${topics}" "/robot/cmd_vel" \
        && contains_line "${topics}" "/roboharness/episode/state" \
        && contains_line "${topics}" "/roboharness/episode/result" \
        && contains_line "${topics}" "/roboharness/task/pointnav" \
        && contains_line "${services}" "/roboharness/env/reset_episode" \
        && contains_line "${services}" "/roboharness/agent/reset_episode"; then
        graph_ready=true
        break
    fi
    sleep 1
done
printf '%s\n' "${nodes}" >"${RUN_DIR}/ros-nodes.txt"
printf '%s\n' "${topics}" >"${RUN_DIR}/ros-topics.txt"
printf '%s\n' "${services}" >"${RUN_DIR}/ros-services.txt"
[[ "${graph_ready}" == true ]] || fail "ROS graph did not become ready before the deadline"

"${COMPOSE[@]}" exec -T experiment "${RUNTIME_ENTRYPOINT}" \
    test -f /opt/roboharness/setup.bash \
    || fail "runtime image does not contain the installed RoboHarness overlay"
"${COMPOSE[@]}" exec -T experiment "${RUNTIME_ENTRYPOINT}" \
    test ! -e /workspace/roboharness \
    || fail "runtime image unexpectedly contains a source workspace"
if "${COMPOSE[@]}" exec -T experiment "${RUNTIME_ENTRYPOINT}" \
    sh -c 'command -v ruff >/dev/null'; then
    fail "runtime image unexpectedly contains the repository lint tool"
fi

container_snapshot >"${RUN_DIR}/containers.before"

result_complete=false
while ((SECONDS < deadline)); do
    if python3 "${ROOT_DIR}/tools/e2e/validate_mock_result.py" \
        --complete-only "${RESULT_DIR}" "${EXPERIMENT_ID}"; then
        result_complete=true
        break
    fi
    sleep 1
done
[[ "${result_complete}" == true ]] || fail "result tree did not complete before the deadline"

container_snapshot >"${RUN_DIR}/containers.after"
cmp --silent "${RUN_DIR}/containers.before" "${RUN_DIR}/containers.after" \
    || fail "one or more runtime containers restarted or exited"

python3 "${ROOT_DIR}/tools/e2e/validate_mock_result.py" \
    "${RESULT_DIR}" "${EXPERIMENT_ID}"
echo "Mock Compose E2E passed. Artifacts: ${RUN_DIR}"
