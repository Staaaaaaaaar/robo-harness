"""Filtering for authoritative Episode snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from rh_interfaces.msg import EpisodeState

from rh_ros.errors import InvalidProtocolValueError


@dataclass(frozen=True, slots=True)
class EpisodeIdentity:
    """Explicit identity of the Episode whose messages may be accepted."""

    experiment_id: str
    episode_id: str

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.episode_id.strip():
            raise InvalidProtocolValueError("experiment_id and episode_id must not be empty")


class EpisodeSequenceGuard:
    """Reject delayed, duplicate, or out-of-order Episode state messages.

    Episode IDs are opaque, so advancing to another Episode is always explicit.
    """

    def __init__(self) -> None:
        self._identity: EpisodeIdentity | None = None
        self._last_sequence: int | None = None

    @property
    def identity(self) -> EpisodeIdentity | None:
        return self._identity

    @property
    def last_sequence(self) -> int | None:
        return self._last_sequence

    def activate(self, experiment_id: str, episode_id: str) -> None:
        """Select a new authoritative Episode and clear sequence history."""

        self._identity = EpisodeIdentity(experiment_id, episode_id)
        self._last_sequence = None

    def accept(self, message: EpisodeState) -> bool:
        """Accept a matching snapshot only when its sequence strictly increases."""

        if self._identity is None:
            return False
        if (
            message.experiment_id != self._identity.experiment_id
            or message.episode_id != self._identity.episode_id
        ):
            return False
        sequence = int(message.sequence)
        if self._last_sequence is not None and sequence <= self._last_sequence:
            return False
        self._last_sequence = sequence
        return True
