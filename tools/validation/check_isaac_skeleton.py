#!/usr/bin/env python3
"""Validate PR 13 files without importing Isaac Sim or requiring a GPU."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DIGEST = re.compile(r"^nvcr\.io/nvidia/isaac-sim:4\.5\.0@sha256:[0-9a-f]{64}$")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def version_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read("deployment/env/versions.env").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", maxsplit=1)
            values[key] = value
    return values


def main() -> int:
    errors: list[str] = []
    versions = version_values()
    if versions.get("RH_ISAAC_SIM_VERSION") != "4.5.0":
        errors.append("RH_ISAAC_SIM_VERSION must remain 4.5.0")
    if not DIGEST.fullmatch(versions.get("RH_ISAAC_SIM_IMAGE", "")):
        errors.append("RH_ISAAC_SIM_IMAGE must pin the 4.5.0 sha256 manifest")
    if any("LAB" in key for key in versions):
        errors.append("Isaac Lab must not be a pinned MVP runtime dependency")

    app = read("simulators/isaac/apps/rh.kit")
    for dependency in (
        '"omni.kit.loop-isaac"',
        '"isaacsim.ros2.bridge"',
        '"rh.isaac"',
    ):
        if dependency not in app:
            errors.append(f"rh.kit is missing dependency {dependency}")

    extension = read("simulators/isaac/extensions/rh.isaac/config/extension.toml")
    if 'name = "rh.isaac"' not in extension:
        errors.append("extension.toml does not expose the rh.isaac Python module")
    extension_init = read(
        "simulators/isaac/extensions/rh.isaac/rh/isaac/__init__.py"
    )
    if "RH_ROS_PYTHON_PATH" not in extension_init:
        errors.append("rh.isaac must register the colcon Python overlay with Kit")

    bridge = yaml.safe_load(read("simulators/isaac/bridge/topics.yaml"))
    clock = bridge.get("native_bridge", {}).get("clock", {})
    if clock.get("topic") != "/clock" or clock.get("type") != "rosgraph_msgs/msg/Clock":
        errors.append("native Bridge mapping must expose rosgraph_msgs/msg/Clock on /clock")

    graph = read(
        "simulators/isaac/extensions/rh.isaac/rh/isaac/clock_graph.py"
    )
    for node_type in (
        "omni.graph.action.OnPlaybackTick",
        "isaacsim.core.nodes.IsaacReadSimulationTime",
        "isaacsim.ros2.bridge.ROS2PublishClock",
    ):
        if node_type not in graph:
            errors.append(f"clock graph is missing native node {node_type}")
    extension_runtime = read(
        "simulators/isaac/extensions/rh.isaac/rh/isaac/extension.py"
    )
    for ready_signal in ("EVENT_APP_READY", "is_app_ready"):
        if ready_signal not in extension_runtime:
            errors.append(f"rh.isaac is missing Kit readiness guard {ready_signal}")

    launcher = read("simulators/isaac/scripts/launch.sh")
    if "isaacsim.exp.base.kit" not in launcher or "--merge-config" not in launcher:
        errors.append("launcher must merge rh.kit over the bundled Isaac base app")
    if '"${ISAAC_APPS_PATH}"' not in launcher:
        errors.append("launcher must register the bundled Isaac apps directory")
    for extension_id in ("isaacsim.ros2.bridge", "rh.isaac"):
        if f"--enable {extension_id}" not in launcher:
            errors.append(f"launcher must explicitly enable {extension_id}")
    if "isaacsim.ros2.bridge/${ROS_DISTRO}/lib" not in launcher:
        errors.append("launcher must expose the bundled Bridge ROS libraries")
    if "/opt/roboharness/local/lib/python3.10/dist-packages" not in launcher:
        errors.append("launcher must expose the merged colcon Python install")
    if "--allow-root" not in launcher:
        errors.append("container launcher must explicitly allow Kit to run as root")

    if errors:
        print("Isaac skeleton validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Isaac Sim image pin, Kit extension, and native clock graph are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
