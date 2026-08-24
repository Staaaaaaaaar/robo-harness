#!/usr/bin/env bash
set -eo pipefail

if [[ "${ACCEPT_EULA:-N}" != "Y" ]]; then
    echo "Isaac Sim EULA is not accepted. Set ACCEPT_EULA=Y in deployment/env/.env." >&2
    exit 64
fi

exec /opt/roboharness/simulators/isaac/scripts/launch.sh "$@"
