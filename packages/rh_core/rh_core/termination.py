"""Deterministic policy for competing Episode termination candidates."""

from __future__ import annotations

from collections.abc import Iterable

from rh_core.models import TerminationReason

# Safety/infrastructure failures outrank operator abort, success, and timeout.
# Within the failure tier, the Environment wins because it is the final motion
# safety boundary. Existing order is domain behavior and must be changed with care.
TERMINATION_PRIORITY: tuple[TerminationReason, ...] = (
    TerminationReason.ENV_ERROR,
    TerminationReason.AGENT_ERROR,
    TerminationReason.FAILURE,
    TerminationReason.INVALID_TASK,
    TerminationReason.ABORTED,
    TerminationReason.SUCCESS,
    TerminationReason.TIMEOUT,
)

_PRIORITY_RANK = {reason: rank for rank, reason in enumerate(TERMINATION_PRIORITY)}


def resolve_termination_reason(
    candidates: Iterable[TerminationReason],
) -> TerminationReason:
    """Select one authoritative reason, or NONE when no candidate exists."""

    effective: set[TerminationReason] = set()
    for reason in candidates:
        if not isinstance(reason, TerminationReason):
            raise TypeError("termination candidates must be TerminationReason values")
        if reason is not TerminationReason.NONE:
            effective.add(reason)
    if not effective:
        return TerminationReason.NONE
    return min(effective, key=_PRIORITY_RANK.__getitem__)
