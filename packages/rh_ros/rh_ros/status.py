"""Status heartbeat publication and steady-clock readiness monitoring."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rh_interfaces.msg import ComponentStatus

from rh_ros.errors import InvalidProtocolValueError
from rh_ros.qos import latched_control_qos

_VALID_STATES = frozenset(
    {
        ComponentStatus.STARTING,
        ComponentStatus.RESETTING,
        ComponentStatus.READY,
        ComponentStatus.ERROR,
    }
)


def _positive_duration(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidProtocolValueError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise InvalidProtocolValueError(f"{name} must be a finite positive number")
    return value


@dataclass(frozen=True, slots=True)
class ReceivedStatus:
    message: ComponentStatus
    received_at: float


class StatusTracker:
    """Store latest status heartbeats and detect staleness using steady time."""

    def __init__(
        self,
        *,
        stale_timeout_s: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stale_timeout_s = _positive_duration(stale_timeout_s, "stale_timeout_s")
        self._monotonic = monotonic
        self._statuses: dict[str, ReceivedStatus] = {}
        self._lock = Lock()

    def update(self, message: ComponentStatus) -> bool:
        """Record a valid heartbeat; malformed messages are ignored."""

        if not message.component_id.strip() or int(message.state) not in _VALID_STATES:
            return False
        received = ReceivedStatus(message=message, received_at=self._monotonic())
        with self._lock:
            self._statuses[message.component_id] = received
        return True

    def latest(self, component_id: str) -> ComponentStatus | None:
        with self._lock:
            status = self._statuses.get(component_id)
        return None if status is None else status.message

    def is_stale(self, component_id: str) -> bool:
        now = self._monotonic()
        with self._lock:
            status = self._statuses.get(component_id)
        return status is None or now - status.received_at > self._stale_timeout_s

    def is_ready(self, component_id: str) -> bool:
        status = self.latest(component_id)
        return (
            status is not None
            and int(status.state) == ComponentStatus.READY
            and not self.is_stale(component_id)
        )


class StatusPublisher:
    """Publish immediate transitions and periodic heartbeats on a steady timer."""

    def __init__(
        self,
        node: Node,
        topic: str,
        component_id: str,
        *,
        heartbeat_period_s: float = 1.0,
    ) -> None:
        if not component_id.strip():
            raise InvalidProtocolValueError("component_id must not be empty")
        heartbeat_period = _positive_duration(heartbeat_period_s, "heartbeat_period_s")
        self._node = node
        self._component_id = component_id
        self._publisher = node.create_publisher(
            ComponentStatus, topic, latched_control_qos()
        )
        self._message: ComponentStatus | None = None
        self._timer = node.create_timer(
            heartbeat_period,
            self.publish,
            clock=Clock(clock_type=ClockType.STEADY_TIME),
        )
        self.transition(ComponentStatus.STARTING)

    @property
    def message(self) -> ComponentStatus:
        if self._message is None:  # pragma: no cover - constructor establishes it
            raise RuntimeError("status publisher is not initialized")
        return self._message

    def transition(
        self,
        state: int,
        *,
        error_code: int = 0,
        detail: str = "",
        restart_required: bool = False,
    ) -> None:
        """Commit a transition timestamp and immediately publish the snapshot."""

        if isinstance(state, bool) or state not in _VALID_STATES:
            raise InvalidProtocolValueError(f"unsupported component state: {state}")
        if (
            isinstance(error_code, bool)
            or not isinstance(error_code, int)
            or not 0 <= error_code <= 2**32 - 1
        ):
            raise InvalidProtocolValueError("error_code must fit in uint32")
        message = ComponentStatus()
        message.stamp = self._node.get_clock().now().to_msg()
        message.component_id = self._component_id
        message.state = state
        message.error_code = error_code
        message.detail = detail
        message.restart_required = restart_required
        self._message = message
        self.publish()

    def publish(self) -> None:
        """Publish the unchanged latest snapshot as a heartbeat."""

        if self._message is not None:
            self._publisher.publish(self._message)


class StatusMonitor:
    """ROS subscription wrapper around :class:`StatusTracker`."""

    def __init__(self, node: Node, topic: str, *, stale_timeout_s: float) -> None:
        self.tracker = StatusTracker(stale_timeout_s=stale_timeout_s)
        self.subscription = node.create_subscription(
            ComponentStatus,
            topic,
            self.tracker.update,
            latched_control_qos(),
        )
