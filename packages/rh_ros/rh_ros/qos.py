"""Canonical QoS profiles for the RoboHarness runtime contract."""

from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    LivelinessPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)


def latched_control_qos() -> QoSProfile:
    """Return the profile for status, state, task, and result snapshots."""

    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        liveliness=LivelinessPolicy.AUTOMATIC,
    )


def command_qos() -> QoSProfile:
    """Return the low-depth reliable profile for robot velocity commands."""

    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        liveliness=LivelinessPolicy.AUTOMATIC,
    )


def sensor_qos() -> QoSProfile:
    """Return an independent copy of the ROS sensor-data profile."""

    return QoSProfile(
        history=qos_profile_sensor_data.history,
        depth=qos_profile_sensor_data.depth,
        reliability=qos_profile_sensor_data.reliability,
        durability=qos_profile_sensor_data.durability,
    )
