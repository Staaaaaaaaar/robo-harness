"""Conversions at the ROS-independent core / ROS wire boundary."""

from __future__ import annotations

import math
from collections.abc import Iterable

from builtin_interfaces.msg import Time
from geometry_msgs.msg import PointStamped, PoseStamped, Quaternion
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rh_interfaces.msg import PointNavTask

from rh_core import (
    EpisodeLifecycle,
    EpisodeSpec,
    EpisodeState,
    Point3D,
    Pose3D,
    TerminationReason,
)
from rh_ros.errors import ConversionError

_QUATERNION_NORM_TOLERANCE = 1e-6


def _finite(values: Iterable[float], description: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ConversionError(f"{description} must contain only finite values")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConversionError(f"{name} must be a non-empty string")


def rpy_to_quaternion(roll: float, pitch: float, yaw: float) -> Quaternion:
    """Convert fixed-axis XYZ roll/pitch/yaw to a normalized quaternion."""

    _finite((roll, pitch, yaw), "roll/pitch/yaw")
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    quaternion = Quaternion()
    quaternion.x = sr * cp * cy - cr * sp * sy
    quaternion.y = cr * sp * cy + sr * cp * sy
    quaternion.z = cr * cp * sy - sr * sp * cy
    quaternion.w = cr * cp * cy + sr * sp * sy
    return quaternion


def quaternion_to_rpy(quaternion: Quaternion) -> tuple[float, float, float]:
    """Validate a wire quaternion and convert it to fixed-axis XYZ RPY."""

    x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
    _finite((x, y, z, w), "quaternion")
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if abs(norm - 1.0) > _QUATERNION_NORM_TOLERANCE:
        raise ConversionError("quaternion must be normalized")

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


def pose_to_message(pose: Pose3D, *, stamp: Time | None = None) -> PoseStamped:
    """Convert a complete core pose to a ROS pose snapshot."""

    _identifier(pose.frame_id, "pose.frame_id")
    _finite((pose.x, pose.y, pose.z, pose.roll, pose.pitch, pose.yaw), "pose")
    message = PoseStamped()
    if stamp is not None:
        message.header.stamp = stamp
    message.header.frame_id = pose.frame_id
    message.pose.position.x = pose.x
    message.pose.position.y = pose.y
    message.pose.position.z = pose.z
    message.pose.orientation = rpy_to_quaternion(pose.roll, pose.pitch, pose.yaw)
    return message


def pose_from_message(message: PoseStamped) -> Pose3D:
    """Convert a ROS pose after finite and quaternion validation."""

    _identifier(message.header.frame_id, "pose.header.frame_id")
    position = message.pose.position
    _finite((position.x, position.y, position.z), "pose.position")
    roll, pitch, yaw = quaternion_to_rpy(message.pose.orientation)
    return Pose3D(
        frame_id=message.header.frame_id,
        x=position.x,
        y=position.y,
        z=position.z,
        roll=roll,
        pitch=pitch,
        yaw=yaw,
    )


def point_to_message(point: Point3D, *, stamp: Time | None = None) -> PointStamped:
    """Convert a core 3D point to a ROS point snapshot."""

    _identifier(point.frame_id, "point.frame_id")
    _finite((point.x, point.y, point.z), "point")
    message = PointStamped()
    if stamp is not None:
        message.header.stamp = stamp
    message.header.frame_id = point.frame_id
    message.point.x = point.x
    message.point.y = point.y
    message.point.z = point.z
    return message


def point_from_message(message: PointStamped) -> Point3D:
    """Convert a finite ROS point snapshot to the core representation."""

    _identifier(message.header.frame_id, "point.header.frame_id")
    _finite((message.point.x, message.point.y, message.point.z), "point")
    return Point3D(
        frame_id=message.header.frame_id,
        x=message.point.x,
        y=message.point.y,
        z=message.point.z,
    )


def pointnav_task_to_message(
    experiment_id: str,
    episode: EpisodeSpec,
    *,
    stamp: Time | None = None,
) -> PointNavTask:
    """Build the immutable PointNav wire snapshot for one Episode."""

    _identifier(experiment_id, "experiment_id")
    _identifier(episode.episode_id, "episode_id")
    task = episode.task
    _finite((task.success_radius_m, task.timeout_s), "PointNav parameters")
    if task.success_radius_m <= 0.0 or task.timeout_s <= 0.0:
        raise ConversionError("PointNav radius and timeout must be positive")
    message = PointNavTask()
    message.experiment_id = experiment_id
    message.episode_id = episode.episode_id
    message.goal = point_to_message(task.goal, stamp=stamp)
    message.success_radius_m = task.success_radius_m
    message.timeout_s = task.timeout_s
    message.seed = episode.seed
    return message


def episode_state_to_message(
    experiment_id: str,
    lifecycle: EpisodeLifecycle,
    *,
    stamp: Time,
    detail: str = "",
) -> EpisodeStateMessage:
    """Convert an authoritative core lifecycle snapshot to its wire form."""

    _identifier(experiment_id, "experiment_id")
    message = EpisodeStateMessage()
    message.stamp = stamp
    message.experiment_id = experiment_id
    message.episode_id = lifecycle.episode_id
    message.sequence = lifecycle.sequence
    message.state = lifecycle.state.value
    message.termination_reason = lifecycle.termination_reason.value
    message.detail = detail
    return message


def episode_state_values_from_message(
    message: EpisodeStateMessage,
) -> tuple[EpisodeState, TerminationReason]:
    """Validate numeric wire values before exposing core enums."""

    try:
        return EpisodeState(message.state), TerminationReason(message.termination_reason)
    except ValueError as error:
        raise ConversionError("EpisodeState contains an unknown numeric value") from error
