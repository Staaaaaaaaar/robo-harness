"""Explicit discovery and call deadlines for short ROS services."""

from __future__ import annotations

import math
from threading import Event
from typing import Any, TypeVar

from rh_ros.errors import (
    InvalidProtocolValueError,
    ServiceCallError,
    ServiceCallTimeoutError,
    ServiceDiscoveryTimeoutError,
)

ResponseT = TypeVar("ResponseT")


def _duration(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidProtocolValueError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise InvalidProtocolValueError(f"{name} must be a finite positive number")
    return value


def call_service_with_deadline(
    client: Any,
    request: Any,
    *,
    discovery_timeout_s: float,
    call_timeout_s: float,
) -> ResponseT:
    """Make a blocking call with separate discovery and completion deadlines.

    The node executor must be spinning on another thread while this function
    waits. Waiting uses OS events and therefore does not depend on simulation
    time. Retries are deliberately left to the caller.
    """

    discovery_timeout = _duration(discovery_timeout_s, "discovery_timeout_s")
    call_timeout = _duration(call_timeout_s, "call_timeout_s")

    if not client.wait_for_service(timeout_sec=discovery_timeout):
        raise ServiceDiscoveryTimeoutError(
            f"service was not discovered within {discovery_timeout:g} seconds"
        )

    future = client.call_async(request)
    completed = Event()
    future.add_done_callback(lambda _: completed.set())
    if not completed.wait(call_timeout):
        future.cancel()
        raise ServiceCallTimeoutError(
            f"service call did not complete within {call_timeout:g} seconds"
        )

    try:
        exception = future.exception()
    except BaseException as error:
        raise ServiceCallError("service future failed") from error
    if exception is not None:
        raise ServiceCallError("service call failed") from exception
    result = future.result()
    if result is None:
        raise ServiceCallError("service call completed without a response")
    return result
