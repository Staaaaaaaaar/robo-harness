from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rh_interfaces.msg import PointNavTask
from rh_interfaces.srv import ResetEnv

import rh_core
from rh_core import (
    EpisodeSpec,
    EpisodeState,
    Point3D,
    PointNavTaskSpec,
    Pose3D,
    TerminationReason,
)


def test_episode_lifecycle_values_match_wire_contract() -> None:
    for name in ("PREPARING", "READY", "RUNNING", "TERMINATING", "FINISHED"):
        assert getattr(EpisodeState, name).value == getattr(EpisodeStateMessage, name)


def test_termination_values_match_wire_contract() -> None:
    for name in (
        "NONE",
        "SUCCESS",
        "TIMEOUT",
        "ABORTED",
        "FAILURE",
        "ENV_ERROR",
        "AGENT_ERROR",
        "INVALID_TASK",
    ):
        assert getattr(TerminationReason, name).value == getattr(EpisodeStateMessage, name)


def test_pointnav_model_maps_losslessly_to_pr2_message() -> None:
    task = PointNavTaskSpec(
        goal=Point3D(frame_id="map", x=8.0, y=4.0, z=1.5),
        success_radius_m=0.5,
        timeout_s=120.0,
    )
    episode = EpisodeSpec(
        episode_id="0000",
        scenario="warehouse_default",
        initial_pose=Pose3D(
            frame_id="map",
            x=1.0,
            y=2.0,
            z=0.4,
            roll=0.0,
            pitch=0.0,
            yaw=0.5,
        ),
        task=task,
        seed=42,
    )

    message = PointNavTask()
    message.experiment_id = "experiment-runtime-id"
    message.episode_id = episode.episode_id
    message.goal.header.frame_id = task.goal.frame_id
    message.goal.point.x = task.goal.x
    message.goal.point.y = task.goal.y
    message.goal.point.z = task.goal.z
    message.success_radius_m = task.success_radius_m
    message.timeout_s = task.timeout_s
    message.seed = episode.seed

    assert message.episode_id == "0000"
    assert message.goal.point.y == 4.0
    assert message.goal.point.z == 1.5
    assert message.success_radius_m == 0.5
    assert message.timeout_s == 120.0
    assert message.seed == 42

    reset = ResetEnv.Request()
    reset.request_id = "reset-0000"
    reset.experiment_id = message.experiment_id
    reset.episode_id = episode.episode_id
    reset.initial_pose.header.frame_id = episode.initial_pose.frame_id
    reset.initial_pose.pose.position.x = episode.initial_pose.x
    reset.initial_pose.pose.position.y = episode.initial_pose.y
    reset.initial_pose.pose.position.z = episode.initial_pose.z

    assert reset.initial_pose.header.frame_id == "map"
    assert reset.initial_pose.pose.position.z == 0.4


def test_core_manifest_has_no_ros_or_implementation_dependencies() -> None:
    manifest = Path(get_package_share_directory("rh_core")) / "package.xml"
    root = ET.parse(manifest).getroot()
    dependency_tags = {
        "buildtool_depend",
        "build_depend",
        "build_export_depend",
        "depend",
        "exec_depend",
    }
    dependencies = {
        element.text.strip()
        for element in root
        if element.tag in dependency_tags and element.text is not None
    }
    assert dependencies == {"ament_python", "python3-yaml"}


def test_core_source_does_not_import_ros_or_implementations() -> None:
    forbidden_roots = {
        "rclpy",
        "rh_interfaces",
        "rh_ros",
        "rh_experiment",
        "isaacsim",
    }
    source_directory = Path(rh_core.__file__).resolve().parent
    violations: list[str] = []

    for source_path in sorted(source_directory.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            imported_roots: list[str] = []
            if isinstance(node, ast.Import):
                imported_roots = [alias.name.split(".", maxsplit=1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots = [node.module.split(".", maxsplit=1)[0]]
            for imported_root in imported_roots:
                if imported_root in forbidden_roots:
                    violations.append(f"{source_path.name}:{node.lineno}: {imported_root}")

    assert violations == []
