import math

import pytest
from builtin_interfaces.msg import Time
from geometry_msgs.msg import PoseStamped, Quaternion

from rh_core import (
    EpisodeLifecycle,
    EpisodeSpec,
    EpisodeState,
    Point3D,
    PointNavTaskSpec,
    Pose3D,
    TerminationReason,
)
from rh_ros import (
    ConversionError,
    episode_state_to_message,
    episode_state_values_from_message,
    pointnav_task_to_message,
    pose_from_message,
    pose_to_message,
    quaternion_to_rpy,
    rpy_to_quaternion,
)


def _episode() -> EpisodeSpec:
    return EpisodeSpec(
        episode_id="episode-1",
        scenario="warehouse",
        initial_pose=Pose3D("map", 1.0, 2.0, 0.4, 0.1, -0.2, 0.3),
        task=PointNavTaskSpec(
            goal=Point3D("map", 8.0, 4.0, 0.4),
            success_radius_m=0.5,
            timeout_s=120.0,
        ),
        seed=42,
    )


def test_full_3d_pose_round_trip() -> None:
    pose = _episode().initial_pose

    recovered = pose_from_message(pose_to_message(pose, stamp=Time(sec=3)))

    assert recovered.frame_id == "map"
    assert recovered.x == pose.x
    assert recovered.y == pose.y
    assert recovered.z == pose.z
    assert recovered.roll == pytest.approx(pose.roll)
    assert recovered.pitch == pytest.approx(pose.pitch)
    assert recovered.yaw == pytest.approx(pose.yaw)


def test_rpy_conversion_produces_normalized_quaternion() -> None:
    quaternion = rpy_to_quaternion(0.4, -0.5, 1.2)
    norm = math.sqrt(
        quaternion.x**2 + quaternion.y**2 + quaternion.z**2 + quaternion.w**2
    )

    assert norm == pytest.approx(1.0)
    assert quaternion_to_rpy(quaternion) == pytest.approx((0.4, -0.5, 1.2))


def test_non_normalized_quaternion_is_rejected() -> None:
    message = PoseStamped()
    message.header.frame_id = "map"
    message.pose.orientation = Quaternion(w=2.0)

    with pytest.raises(ConversionError, match="normalized"):
        pose_from_message(message)


def test_pointnav_message_contains_position_but_no_target_orientation() -> None:
    message = pointnav_task_to_message("experiment-1", _episode(), stamp=Time(sec=5))

    assert message.experiment_id == "experiment-1"
    assert message.episode_id == "episode-1"
    assert message.goal.header.frame_id == "map"
    assert (message.goal.point.x, message.goal.point.y, message.goal.point.z) == (
        8.0,
        4.0,
        0.4,
    )
    assert not hasattr(message.goal, "pose")
    assert message.seed == 42


def test_lifecycle_values_convert_without_reinterpreting_wire_constants() -> None:
    lifecycle = EpisodeLifecycle(episode_id="episode-1").transition(EpisodeState.READY)
    message = episode_state_to_message(
        "experiment-1", lifecycle, stamp=Time(sec=7), detail="ready"
    )

    state, reason = episode_state_values_from_message(message)

    assert state is EpisodeState.READY
    assert reason is TerminationReason.NONE
    assert message.sequence == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_pose_is_rejected(value: float) -> None:
    pose = Pose3D("map", value, 0.0, 0.0, 0.0, 0.0, 0.0)

    with pytest.raises(ConversionError, match="finite"):
        pose_to_message(pose)
