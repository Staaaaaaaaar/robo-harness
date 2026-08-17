from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSCompatibility,
    ReliabilityPolicy,
    qos_check_compatible,
)

from rh_ros import command_qos, latched_control_qos, sensor_qos


def test_control_snapshot_profile_is_latched_and_reliable() -> None:
    profile = latched_control_qos()

    assert profile.history is HistoryPolicy.KEEP_LAST
    assert profile.depth == 1
    assert profile.reliability is ReliabilityPolicy.RELIABLE
    assert profile.durability is DurabilityPolicy.TRANSIENT_LOCAL


def test_profile_factories_return_independent_values() -> None:
    first = latched_control_qos()
    second = latched_control_qos()

    first.depth = 7

    assert second.depth == 1


def test_control_publishers_and_subscribers_are_compatible() -> None:
    compatibility, reason = qos_check_compatible(
        latched_control_qos(), latched_control_qos()
    )

    assert compatibility == QoSCompatibility.OK
    assert reason == ""


def test_standard_data_plane_profiles_have_expected_reliability() -> None:
    assert command_qos().reliability is ReliabilityPolicy.RELIABLE
    assert command_qos().depth == 1
    assert sensor_qos().reliability is ReliabilityPolicy.BEST_EFFORT
