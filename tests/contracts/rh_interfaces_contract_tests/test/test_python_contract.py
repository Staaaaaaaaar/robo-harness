from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from ament_index_python.packages import get_package_share_directory
from rclpy.serialization import deserialize_message, serialize_message
from rh_interfaces.msg import (
    AgentTaskState,
    ComponentStatus,
    EpisodeResult,
    EpisodeState,
    PointNavTask,
)
from rh_interfaces.srv import AbortEpisode, ResetAgent, ResetEnv, StartEpisode


def test_stable_numeric_constants() -> None:
    assert {
        "IDLE": AgentTaskState.IDLE,
        "RUNNING": AgentTaskState.RUNNING,
        "SUCCEEDED": AgentTaskState.SUCCEEDED,
        "FAILED": AgentTaskState.FAILED,
    } == {"IDLE": 0, "RUNNING": 1, "SUCCEEDED": 2, "FAILED": 3}

    assert {
        "STARTING": ComponentStatus.STARTING,
        "RESETTING": ComponentStatus.RESETTING,
        "READY": ComponentStatus.READY,
        "ERROR": ComponentStatus.ERROR,
    } == {"STARTING": 0, "RESETTING": 1, "READY": 2, "ERROR": 3}

    assert {
        "PREPARING": EpisodeState.PREPARING,
        "READY": EpisodeState.READY,
        "RUNNING": EpisodeState.RUNNING,
        "TERMINATING": EpisodeState.TERMINATING,
        "FINISHED": EpisodeState.FINISHED,
    } == {"PREPARING": 0, "READY": 1, "RUNNING": 2, "TERMINATING": 3, "FINISHED": 4}

    assert {
        "NONE": EpisodeState.NONE,
        "SUCCESS": EpisodeState.SUCCESS,
        "TIMEOUT": EpisodeState.TIMEOUT,
        "ABORTED": EpisodeState.ABORTED,
        "FAILURE": EpisodeState.FAILURE,
        "ENV_ERROR": EpisodeState.ENV_ERROR,
        "AGENT_ERROR": EpisodeState.AGENT_ERROR,
        "INVALID_TASK": EpisodeState.INVALID_TASK,
    } == {
        "NONE": 0,
        "SUCCESS": 1,
        "TIMEOUT": 2,
        "ABORTED": 3,
        "FAILURE": 4,
        "ENV_ERROR": 5,
        "AGENT_ERROR": 6,
        "INVALID_TASK": 7,
    }


@pytest.mark.parametrize(
    ("interface_type", "expected_fields"),
    [
        (
            AgentTaskState,
            {
                "stamp": "builtin_interfaces/Time",
                "experiment_id": "string",
                "episode_id": "string",
                "sequence": "uint64",
                "state": "uint8",
                "detail": "string",
            },
        ),
        (
            ComponentStatus,
            {
                "stamp": "builtin_interfaces/Time",
                "component_id": "string",
                "state": "uint8",
                "error_code": "uint32",
                "detail": "string",
                "restart_required": "boolean",
            },
        ),
        (
            EpisodeState,
            {
                "stamp": "builtin_interfaces/Time",
                "experiment_id": "string",
                "episode_id": "string",
                "sequence": "uint64",
                "state": "uint8",
                "termination_reason": "uint8",
                "detail": "string",
            },
        ),
        (
            PointNavTask,
            {
                "experiment_id": "string",
                "episode_id": "string",
                "goal": "geometry_msgs/PointStamped",
                "success_radius_m": "double",
                "timeout_s": "double",
                "seed": "int64",
            },
        ),
        (
            EpisodeResult,
            {
                "experiment_id": "string",
                "episode_id": "string",
                "termination_reason": "uint8",
                "success": "boolean",
                "elapsed_time_s": "double",
                "path_length_m": "double",
                "final_distance_to_goal_m": "double",
                "result_uri": "string",
            },
        ),
        (
            ResetEnv.Request,
            {
                "request_id": "string",
                "experiment_id": "string",
                "episode_id": "string",
                "initial_pose": "geometry_msgs/PoseStamped",
                "seed": "int64",
            },
        ),
        (
            ResetEnv.Response,
            {"success": "boolean", "error_code": "uint32", "detail": "string"},
        ),
        (
            ResetAgent.Request,
            {"request_id": "string", "experiment_id": "string", "episode_id": "string"},
        ),
        (
            ResetAgent.Response,
            {"success": "boolean", "error_code": "uint32", "detail": "string"},
        ),
        (
            StartEpisode.Request,
            {"experiment_id": "string", "episode_id": "string"},
        ),
        (
            StartEpisode.Response,
            {"accepted": "boolean", "detail": "string"},
        ),
        (
            AbortEpisode.Request,
            {"experiment_id": "string", "episode_id": "string", "reason": "string"},
        ),
        (
            AbortEpisode.Response,
            {"accepted": "boolean", "detail": "string"},
        ),
    ],
)
def test_field_names_order_and_types_are_stable(
    interface_type: type, expected_fields: dict[str, str]
) -> None:
    assert interface_type.get_fields_and_field_types() == expected_fields


@pytest.mark.parametrize(
    "instance",
    [
        AgentTaskState(
            experiment_id="experiment-1",
            episode_id="episode-1",
            sequence=2,
            state=AgentTaskState.SUCCEEDED,
        ),
        ComponentStatus(component_id="env", state=ComponentStatus.READY),
        EpisodeState(
            experiment_id="experiment-1",
            episode_id="episode-1",
            sequence=4,
            state=EpisodeState.FINISHED,
            termination_reason=EpisodeState.SUCCESS,
        ),
        PointNavTask(
            experiment_id="experiment-1",
            episode_id="episode-1",
            success_radius_m=0.5,
            timeout_s=60.0,
            seed=42,
        ),
        EpisodeResult(
            experiment_id="experiment-1",
            episode_id="episode-1",
            termination_reason=EpisodeState.SUCCESS,
            success=True,
            elapsed_time_s=12.5,
            path_length_m=4.25,
            final_distance_to_goal_m=0.3,
            result_uri="results/experiment-1/episode-1/result.json",
        ),
        ResetEnv.Request(request_id="request-1", episode_id="episode-1", seed=42),
        ResetEnv.Response(success=True),
        ResetAgent.Request(request_id="request-2", episode_id="episode-1"),
        ResetAgent.Response(success=True),
        StartEpisode.Request(experiment_id="experiment-1", episode_id="episode-1"),
        StartEpisode.Response(accepted=True),
        AbortEpisode.Request(episode_id="episode-1", reason="operator request"),
        AbortEpisode.Response(accepted=True),
    ],
)
def test_python_serialization_round_trip(instance: object) -> None:
    restored = deserialize_message(serialize_message(instance), type(instance))
    assert restored == instance


def test_interface_package_has_only_allowed_dependencies() -> None:
    manifest = Path(get_package_share_directory("rh_interfaces")) / "package.xml"
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

    assert dependencies == {
        "ament_cmake",
        "builtin_interfaces",
        "geometry_msgs",
        "rosidl_default_generators",
        "rosidl_default_runtime",
    }
