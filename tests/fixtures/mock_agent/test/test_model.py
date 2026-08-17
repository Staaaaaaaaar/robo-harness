import pytest

from rh_mock_agent.model import (
    ZERO_COMMAND,
    MockAgentModel,
    ScriptSegment,
    VelocityCommand,
)


@pytest.fixture
def model() -> MockAgentModel:
    return MockAgentModel(
        (
            ScriptSegment(1_000_000_000, VelocityCommand(linear_x=0.5)),
            ScriptSegment(500_000_000, VelocityCommand(angular_z=1.0)),
        )
    )


def test_reset_clears_task_running_clock_and_command(model: MockAgentModel) -> None:
    model.reset("experiment-1", "episode-1")
    assert model.accept_task("experiment-1", "episode-1", ("task",))
    model.set_episode_running(True)
    model.advance_clock(1_000_000_000)
    model.advance_clock(1_200_000_000)

    model.reset("experiment-1", "episode-2")

    assert model.snapshot.episode_id == "episode-2"
    assert model.snapshot.task_fingerprint is None
    assert not model.snapshot.episode_running
    assert model.snapshot.script_elapsed_ns == 0
    assert model.snapshot.command == ZERO_COMMAND


def test_task_and_running_state_both_gate_script(model: MockAgentModel) -> None:
    model.reset("experiment-1", "episode-1")
    model.set_episode_running(True)
    assert model.snapshot.command == ZERO_COMMAND
    assert not model.accept_task("experiment-1", "other", ("wrong",))

    assert model.accept_task("experiment-1", "episode-1", ("task",))
    assert model.snapshot.command.linear_x == pytest.approx(0.5)

    model.set_episode_running(False)
    assert model.snapshot.command == ZERO_COMMAND


def test_script_uses_simulation_time_and_stops_at_end(model: MockAgentModel) -> None:
    model.reset("experiment-1", "episode-1")
    model.accept_task("experiment-1", "episode-1", ("task",))
    model.set_episode_running(True)

    model.advance_clock(10_000_000_000)
    model.advance_clock(10_999_999_999)
    assert model.snapshot.command.linear_x == pytest.approx(0.5)
    model.advance_clock(11_000_000_000)
    assert model.snapshot.command.angular_z == pytest.approx(1.0)
    model.advance_clock(11_500_000_000)
    assert model.snapshot.command == ZERO_COMMAND


def test_conflicting_task_and_backward_clock_do_not_leak_motion(
    model: MockAgentModel,
) -> None:
    model.reset("experiment-1", "episode-1")
    assert model.accept_task("experiment-1", "episode-1", ("original",))
    assert not model.accept_task("experiment-1", "episode-1", ("conflict",))
    model.set_episode_running(True)
    model.advance_clock(100)
    assert model.snapshot.command != ZERO_COMMAND

    assert not model.advance_clock(99)
    assert model.snapshot.command == ZERO_COMMAND


@pytest.mark.parametrize("duration_ns", [0, -1, True])
def test_script_rejects_invalid_duration(duration_ns: int) -> None:
    with pytest.raises(ValueError, match="duration"):
        ScriptSegment(duration_ns, ZERO_COMMAND)
