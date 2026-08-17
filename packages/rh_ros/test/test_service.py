from concurrent.futures import Future
from threading import Timer
from typing import Any

import pytest

from rh_ros import (
    InvalidProtocolValueError,
    ServiceCallError,
    ServiceCallTimeoutError,
    ServiceDiscoveryTimeoutError,
    call_service_with_deadline,
)


class FakeClient:
    def __init__(self, *, discovered: bool, future: Future[Any] | None = None) -> None:
        self.discovered = discovered
        self.future = future or Future()
        self.discovery_timeout: float | None = None

    def wait_for_service(self, *, timeout_sec: float) -> bool:
        self.discovery_timeout = timeout_sec
        return self.discovered

    def call_async(self, request: object) -> Future[Any]:
        return self.future


def test_service_discovery_timeout_is_distinct() -> None:
    client = FakeClient(discovered=False)

    with pytest.raises(ServiceDiscoveryTimeoutError):
        call_service_with_deadline(
            client,
            object(),
            discovery_timeout_s=0.01,
            call_timeout_s=0.01,
        )

    assert client.discovery_timeout == 0.01


def test_service_call_timeout_cancels_future() -> None:
    future: Future[object] = Future()
    client = FakeClient(discovered=True, future=future)

    with pytest.raises(ServiceCallTimeoutError):
        call_service_with_deadline(
            client,
            object(),
            discovery_timeout_s=0.01,
            call_timeout_s=0.01,
        )

    assert future.cancelled()


def test_completed_service_response_is_returned() -> None:
    future: Future[str] = Future()
    Timer(0.01, lambda: future.set_result("response")).start()

    result = call_service_with_deadline(
        FakeClient(discovered=True, future=future),
        object(),
        discovery_timeout_s=0.1,
        call_timeout_s=0.2,
    )

    assert result == "response"


def test_service_future_exception_is_structured() -> None:
    future: Future[object] = Future()
    future.set_exception(RuntimeError("server exploded"))

    with pytest.raises(ServiceCallError) as captured:
        call_service_with_deadline(
            FakeClient(discovered=True, future=future),
            object(),
            discovery_timeout_s=0.1,
            call_timeout_s=0.1,
        )

    assert isinstance(captured.value.__cause__, RuntimeError)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), True])
def test_invalid_deadline_is_rejected(timeout: float) -> None:
    with pytest.raises(InvalidProtocolValueError):
        call_service_with_deadline(
            FakeClient(discovered=True),
            object(),
            discovery_timeout_s=timeout,
            call_timeout_s=1.0,
        )
