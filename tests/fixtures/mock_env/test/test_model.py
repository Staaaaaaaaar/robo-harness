import math

import pytest

from rh_core import Pose3D
from rh_mock_env import ZERO_COMMAND, MockEnvironmentModel, VelocityCommand


def _pose(*, yaw: float = 0.0) -> Pose3D:
    return Pose3D("map", 1.0, 2.0, 0.4, 0.1, -0.2, yaw)


def test_reset_preserves_complete_pose_and_global_simulation_time() -> None:
    model = MockEnvironmentModel(command_timeout_s=0.5)
    model.step(100_000_000)

    model.reset(_pose(yaw=0.3))

    assert model.snapshot.pose == _pose(yaw=0.3)
    assert model.snapshot.simulation_time_ns == 100_000_000
    assert model.snapshot.command == ZERO_COMMAND
    assert not model.snapshot.episode_running


def test_non_running_gate_rejects_motion() -> None:
    model = MockEnvironmentModel(command_timeout_s=0.5)
    model.reset(_pose())

    assert not model.receive_command(VelocityCommand(linear_x=1.0))
    model.step(100_000_000)

    assert model.snapshot.pose == _pose()
    assert model.snapshot.command == ZERO_COMMAND


def test_fixed_step_motion_is_deterministic_in_body_frame() -> None:
    model = MockEnvironmentModel(command_timeout_s=1.0)
    model.reset(_pose(yaw=math.pi / 2.0))
    model.set_episode_running(True)
    assert model.receive_command(VelocityCommand(linear_x=2.0, angular_z=0.5))

    model.step(100_000_000)

    assert model.snapshot.pose.x == pytest.approx(1.0)
    assert model.snapshot.pose.y == pytest.approx(2.2)
    assert model.snapshot.pose.z == 0.4
    assert model.snapshot.pose.roll == 0.1
    assert model.snapshot.pose.pitch == -0.2
    assert model.snapshot.pose.yaw == pytest.approx(math.pi / 2.0 + 0.05)


def test_leaving_running_state_immediately_zeros_command() -> None:
    model = MockEnvironmentModel(command_timeout_s=1.0)
    model.reset(_pose())
    model.set_episode_running(True)
    model.receive_command(VelocityCommand(linear_x=1.0))

    model.set_episode_running(False)
    model.step(100_000_000)

    assert model.snapshot.command == ZERO_COMMAND
    assert model.snapshot.pose == _pose()


def test_simulation_time_watchdog_stops_stale_command() -> None:
    model = MockEnvironmentModel(command_timeout_s=0.2)
    model.reset(_pose())
    model.set_episode_running(True)
    model.receive_command(VelocityCommand(linear_x=1.0))

    model.step(100_000_000)
    model.step(100_000_000)
    assert model.snapshot.pose.x == pytest.approx(1.2)

    model.step(100_000_000)
    assert model.snapshot.pose.x == pytest.approx(1.2)
    assert model.snapshot.command == ZERO_COMMAND


@pytest.mark.parametrize(
    "command",
    [
        VelocityCommand(linear_x=float("nan")),
        VelocityCommand(linear_y=float("inf")),
        VelocityCommand(angular_z=float("-inf")),
    ],
)
def test_non_finite_command_is_rejected_and_zeroed(command: VelocityCommand) -> None:
    model = MockEnvironmentModel(command_timeout_s=1.0)
    model.set_episode_running(True)
    model.receive_command(VelocityCommand(linear_x=1.0))

    assert not model.receive_command(command)
    assert model.snapshot.command == ZERO_COMMAND


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_watchdog_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        MockEnvironmentModel(command_timeout_s=timeout)
