import pytest

from rh_core import EpisodeState, ExecutionMode, ExperimentState, TerminationReason
from rh_experiment import SingleEpisodeController


@pytest.fixture
def controller() -> SingleEpisodeController:
    return SingleEpisodeController(
        experiment_id="experiment-1",
        episode_id="episode-1",
        execution_mode=ExecutionMode.MANUAL,
    )


def test_happy_path_commits_one_reason(controller: SingleEpisodeController) -> None:
    controller.mark_components_ready()
    controller.mark_prepared()
    assert controller.request_start("experiment-1", "episode-1").accepted
    assert controller.request_termination(
        TerminationReason.SUCCESS, detail="goal reached"
    ).accepted
    assert not controller.request_termination(
        TerminationReason.TIMEOUT, detail="late timeout"
    ).accepted

    controller.finish_termination()

    assert controller.episode.state is EpisodeState.FINISHED
    assert controller.episode.termination_reason is TerminationReason.SUCCESS
    assert controller.episode.sequence == 4
    assert controller.experiment.state is ExperimentState.FINISHED


def test_start_requires_exact_identity_and_ready_state(
    controller: SingleEpisodeController,
) -> None:
    assert not controller.request_start("experiment-1", "episode-1").accepted
    controller.mark_components_ready()
    controller.mark_prepared()
    assert not controller.request_start("wrong", "episode-1").accepted
    assert not controller.request_start("experiment-1", "wrong").accepted
    assert controller.request_start("experiment-1", "episode-1").accepted
    assert not controller.request_start("experiment-1", "episode-1").accepted


def test_abort_is_valid_while_ready_and_rejects_empty_reason(
    controller: SingleEpisodeController,
) -> None:
    controller.mark_components_ready()
    controller.mark_prepared()
    assert not controller.request_abort("experiment-1", "episode-1", " ").accepted
    assert controller.request_abort(
        "experiment-1", "episode-1", "operator request"
    ).accepted
    assert controller.episode.termination_reason is TerminationReason.ABORTED


def test_startup_failure_finishes_episode_and_fails_experiment(
    controller: SingleEpisodeController,
) -> None:
    assert controller.request_termination(
        TerminationReason.ENV_ERROR, detail="environment unavailable"
    ).accepted
    controller.finish_termination()
    assert controller.episode.state is EpisodeState.FINISHED
    assert controller.experiment.state is ExperimentState.FAILED
