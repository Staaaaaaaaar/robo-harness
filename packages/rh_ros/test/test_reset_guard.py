from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from rh_ros import (
    IdempotentResetGuard,
    InvalidProtocolValueError,
    ResetRequestConflictError,
)


def test_duplicate_reset_replays_result_without_reexecution() -> None:
    guard: IdempotentResetGuard[tuple[str, str], object] = IdempotentResetGuard()
    calls = 0
    expected = object()

    def reset() -> object:
        nonlocal calls
        calls += 1
        return expected

    first = guard.execute("request-1", ("experiment", "episode"), reset)
    duplicate = guard.execute("request-1", ("experiment", "episode"), reset)

    assert first is expected
    assert duplicate is expected
    assert calls == 1


def test_concurrent_duplicates_execute_only_once() -> None:
    guard: IdempotentResetGuard[tuple[str, str], int] = IdempotentResetGuard()
    barrier = Barrier(5)
    call_lock = Lock()
    calls = 0

    def invoke() -> int:
        barrier.wait()

        def reset() -> int:
            nonlocal calls
            with call_lock:
                calls += 1
            return 42

        return guard.execute("request-1", ("experiment", "episode"), reset)

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: invoke(), range(5)))

    assert results == [42] * 5
    assert calls == 1


def test_request_id_reuse_with_different_content_is_rejected() -> None:
    guard: IdempotentResetGuard[tuple[str, str], bool] = IdempotentResetGuard()
    guard.execute("request-1", ("experiment", "episode-1"), lambda: True)

    with pytest.raises(ResetRequestConflictError):
        guard.execute("request-1", ("experiment", "episode-2"), lambda: True)


def test_operation_failure_is_replayed_without_an_unsafe_retry() -> None:
    guard: IdempotentResetGuard[str, bool] = IdempotentResetGuard()
    calls = 0

    def reset() -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("backend failed after reset began")

    with pytest.raises(RuntimeError, match="backend failed"):
        guard.execute("request-1", "fingerprint", reset)
    with pytest.raises(RuntimeError, match="backend failed"):
        guard.execute("request-1", "fingerprint", reset)

    assert calls == 1


def test_capacity_is_bounded_and_old_completed_ids_can_expire() -> None:
    guard: IdempotentResetGuard[str, int] = IdempotentResetGuard(capacity=2)
    calls = 0

    def reset() -> int:
        nonlocal calls
        calls += 1
        return calls

    guard.execute("request-1", "same", reset)
    guard.execute("request-2", "same", reset)
    guard.execute("request-3", "same", reset)

    assert guard.execute("request-1", "same", reset) == 4


@pytest.mark.parametrize("capacity", [0, -1, True])
def test_invalid_capacity_is_rejected(capacity: int) -> None:
    with pytest.raises(InvalidProtocolValueError):
        IdempotentResetGuard(capacity=capacity)
