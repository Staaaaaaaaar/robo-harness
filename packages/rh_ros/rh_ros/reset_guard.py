"""Thread-safe idempotency guard for reset service implementations."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from threading import Condition
from typing import Generic, TypeVar

from rh_ros.errors import InvalidProtocolValueError, ResetRequestConflictError

FingerprintT = TypeVar("FingerprintT", bound=Hashable)
ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class _Record(Generic[FingerprintT, ResultT]):
    fingerprint: FingerprintT
    complete: bool = False
    result: ResultT | None = None
    error: BaseException | None = None


class IdempotentResetGuard(Generic[FingerprintT, ResultT]):
    """Execute one reset per request ID and replay its completed result.

    The caller supplies a hashable fingerprint containing every behaviorally
    relevant request field. Reusing an ID with a different fingerprint is a
    protocol conflict rather than a second reset.
    """

    def __init__(self, *, capacity: int = 128) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise InvalidProtocolValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._records: OrderedDict[str, _Record[FingerprintT, ResultT]] = OrderedDict()
        self._condition = Condition()

    def execute(
        self,
        request_id: str,
        fingerprint: FingerprintT,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        """Return the original result for all equivalent duplicate requests."""

        if not isinstance(request_id, str) or not request_id.strip():
            raise InvalidProtocolValueError("request_id must be a non-empty string")

        with self._condition:
            record = self._records.get(request_id)
            if record is not None:
                if record.fingerprint != fingerprint:
                    raise ResetRequestConflictError(
                        f"request_id {request_id!r} was reused with different content"
                    )
                while not record.complete:
                    self._condition.wait()
                self._records.move_to_end(request_id)
                if record.error is not None:
                    raise record.error
                return record.result  # type: ignore[return-value]

            record = _Record(fingerprint=fingerprint)
            self._records[request_id] = record

        try:
            result = operation()
        except BaseException as error:
            with self._condition:
                record.error = error
                record.complete = True
                self._records.move_to_end(request_id)
                self._evict_completed()
                self._condition.notify_all()
            raise

        with self._condition:
            record.result = result
            record.complete = True
            self._records.move_to_end(request_id)
            self._evict_completed()
            self._condition.notify_all()
        return result

    def _evict_completed(self) -> None:
        completed = sum(record.complete for record in self._records.values())
        for request_id in tuple(self._records):
            if completed <= self._capacity:
                break
            if self._records[request_id].complete:
                del self._records[request_id]
                completed -= 1
