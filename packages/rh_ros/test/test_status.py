from __future__ import annotations

import time
from uuid import uuid4

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rh_interfaces.msg import ComponentStatus

from rh_ros import (
    InvalidProtocolValueError,
    StatusMonitor,
    StatusPublisher,
    StatusTracker,
)


class FakeSteadyClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _status(component_id: str, state: int) -> ComponentStatus:
    message = ComponentStatus()
    message.component_id = component_id
    message.state = state
    return message


def test_tracker_detects_missing_and_stale_heartbeats() -> None:
    clock = FakeSteadyClock()
    tracker = StatusTracker(stale_timeout_s=5.0, monotonic=clock)

    assert tracker.is_stale("env")
    assert tracker.update(_status("env", ComponentStatus.READY))
    assert tracker.is_ready("env")

    clock.now = 5.0
    assert not tracker.is_stale("env")
    clock.now = 5.001
    assert tracker.is_stale("env")
    assert not tracker.is_ready("env")


def test_tracker_ignores_malformed_status() -> None:
    tracker = StatusTracker(stale_timeout_s=5.0)

    assert not tracker.update(_status("", ComponentStatus.READY))
    assert not tracker.update(_status("env", 255))
    assert tracker.latest("env") is None


def test_heartbeat_fault_injection_requires_a_bool(ros_context: None) -> None:
    node = rclpy.create_node("status_heartbeat_control_test")
    try:
        publisher = StatusPublisher(node, "/roboharness/test/heartbeat_control", "env")
        with pytest.raises(InvalidProtocolValueError, match="enabled must be a bool"):
            publisher.set_heartbeat_enabled(1)  # type: ignore[arg-type]
        publisher.set_heartbeat_enabled(False)
        publisher.set_heartbeat_enabled(True)
    finally:
        node.destroy_node()


@pytest.fixture
def ros_context() -> None:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def test_late_join_monitor_receives_retained_status_and_transition_stamp_is_stable(
    ros_context: None,
) -> None:
    topic = f"/roboharness/test/status_{uuid4().hex}"
    publisher_node = rclpy.create_node("status_publisher_test")
    monitor_node = rclpy.create_node("status_monitor_test")
    executor = SingleThreadedExecutor()
    try:
        publisher = StatusPublisher(
            publisher_node,
            topic,
            "env",
            heartbeat_period_s=0.05,
        )
        publisher.transition(ComponentStatus.READY, detail="ready")
        transition_stamp = (
            publisher.message.stamp.sec,
            publisher.message.stamp.nanosec,
        )

        # The subscription is intentionally created after the transition publish.
        monitor = StatusMonitor(monitor_node, topic, stale_timeout_s=1.0)
        executor.add_node(publisher_node)
        executor.add_node(monitor_node)
        deadline = time.monotonic() + 5.0
        while monitor.tracker.latest("env") is None and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)

        received = monitor.tracker.latest("env")
        assert received is not None
        assert received.state == ComponentStatus.READY
        assert (received.stamp.sec, received.stamp.nanosec) == transition_stamp

        # Let a heartbeat fire; it republishes rather than committing a transition.
        heartbeat_deadline = time.monotonic() + 0.2
        while time.monotonic() < heartbeat_deadline:
            executor.spin_once(timeout_sec=0.05)
        assert (
            publisher.message.stamp.sec,
            publisher.message.stamp.nanosec,
        ) == transition_stamp
    finally:
        executor.shutdown()
        publisher_node.destroy_node()
        monitor_node.destroy_node()
