import pytest
from rh_interfaces.msg import EpisodeState

from rh_ros import EpisodeSequenceGuard, InvalidProtocolValueError


def _message(experiment_id: str, episode_id: str, sequence: int) -> EpisodeState:
    message = EpisodeState()
    message.experiment_id = experiment_id
    message.episode_id = episode_id
    message.sequence = sequence
    return message


def test_sequence_guard_requires_explicit_episode_activation() -> None:
    guard = EpisodeSequenceGuard()

    assert not guard.accept(_message("experiment", "episode-1", 0))


def test_sequence_guard_rejects_wrong_episode_and_non_increasing_sequence() -> None:
    guard = EpisodeSequenceGuard()
    guard.activate("experiment", "episode-1")

    assert guard.accept(_message("experiment", "episode-1", 0))
    assert not guard.accept(_message("experiment", "episode-1", 0))
    assert not guard.accept(_message("experiment", "episode-1", 0))
    assert not guard.accept(_message("experiment", "episode-2", 1))
    assert not guard.accept(_message("old-experiment", "episode-1", 1))
    assert guard.accept(_message("experiment", "episode-1", 2))


def test_activating_new_opaque_episode_resets_sequence_tracking() -> None:
    guard = EpisodeSequenceGuard()
    guard.activate("experiment", "z-last")
    assert guard.accept(_message("experiment", "z-last", 9))

    guard.activate("experiment", "a-next")

    assert guard.last_sequence is None
    assert guard.accept(_message("experiment", "a-next", 0))


@pytest.mark.parametrize(("experiment_id", "episode_id"), [("", "episode"), ("exp", " ")])
def test_activation_rejects_empty_identifiers(experiment_id: str, episode_id: str) -> None:
    with pytest.raises(InvalidProtocolValueError):
        EpisodeSequenceGuard().activate(experiment_id, episode_id)
