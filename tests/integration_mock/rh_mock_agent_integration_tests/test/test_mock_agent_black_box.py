from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
import rclpy
from geometry_msgs.msg import Twist
from rclpy.client import Client
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import AgentTaskState, ComponentStatus, EpisodeState, PointNavTask
from rh_interfaces.srv import ResetAgent
from rosgraph_msgs.msg import Clock

from rh_mock_agent.node import RESET_ID_CONFLICT, MockAgentNode
from rh_ros import StatusMonitor, command_qos, latched_control_qos


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _client_node(prefix: str) -> Node:
    return rclpy.create_node(f"{prefix}_{uuid4().hex}")


def _spin_for(executor: SingleThreadedExecutor, duration_s: float) -> None:
    deadline = time.monotonic() + duration_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        executor.spin_once(timeout_sec=min(0.02, remaining))


def _spin_until(
    executor: SingleThreadedExecutor,
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert predicate()


def _reset_request(
    *, request_id: str = "reset-1", episode_id: str = "episode-1"
) -> ResetAgent.Request:
    request = ResetAgent.Request()
    request.request_id = request_id
    request.experiment_id = "experiment-1"
    request.episode_id = episode_id
    return request


def _call_reset(
    executor: SingleThreadedExecutor,
    client: Client,
    request: ResetAgent.Request,
) -> ResetAgent.Response:
    assert client.wait_for_service(timeout_sec=2.0)
    future = client.call_async(request)
    _spin_until(executor, future.done)
    result = future.result()
    assert result is not None
    return result


def _episode_state(
    state: int, sequence: int, *, episode_id: str = "episode-1"
) -> EpisodeState:
    message = EpisodeState()
    message.experiment_id = "experiment-1"
    message.episode_id = episode_id
    message.sequence = sequence
    message.state = state
    message.termination_reason = EpisodeState.NONE
    return message


def _task(*, episode_id: str = "episode-1", goal_x: float = 2.0) -> PointNavTask:
    message = PointNavTask()
    message.experiment_id = "experiment-1"
    message.episode_id = episode_id
    message.goal.header.frame_id = "map"
    message.goal.point.x = goal_x
    message.goal.point.y = 1.0
    message.goal.point.z = 0.2
    message.success_radius_m = 0.25
    message.timeout_s = 30.0
    message.seed = 42
    return message


def _clock(nanoseconds: int) -> Clock:
    message = Clock()
    message.clock.sec, message.clock.nanosec = divmod(nanoseconds, 1_000_000_000)
    return message


def _is_zero(command: Twist) -> bool:
    return (
        command.linear.x == 0.0
        and command.linear.y == 0.0
        and command.angular.z == 0.0
    )


def test_readiness_is_latched_and_never_ready_is_observable(
    ros_context: None,
) -> None:
    ready_agent = MockAgentNode(node_name="mock_agent_ready")
    client = _client_node("mock_agent_status_observer")
    executor = SingleThreadedExecutor()
    try:
        status = StatusMonitor(client, "/roboharness/agent/status", stale_timeout_s=2.0)
        executor.add_node(ready_agent)
        executor.add_node(client)
        _spin_until(executor, lambda: status.tracker.is_ready("mock_agent"))
    finally:
        executor.shutdown()
        ready_agent.destroy_node()
        client.destroy_node()

    blocked_agent = MockAgentNode(
        node_name="mock_agent_never_ready",
        parameter_overrides=[Parameter("never_ready", value=True)],
    )
    client = _client_node("mock_agent_startup_observer")
    executor = SingleThreadedExecutor()
    try:
        status = StatusMonitor(client, "/roboharness/agent/status", stale_timeout_s=2.0)
        executor.add_node(blocked_agent)
        executor.add_node(client)
        _spin_until(
            executor,
            lambda: status.tracker.latest("mock_agent") is not None,
        )
        assert status.tracker.latest("mock_agent").state == ComponentStatus.STARTING
        assert not status.tracker.is_ready("mock_agent")
    finally:
        executor.shutdown()
        blocked_agent.destroy_node()
        client.destroy_node()


def test_reset_task_state_and_simulation_clock_gate_the_script(
    ros_context: None,
) -> None:
    agent = MockAgentNode(
        node_name="mock_agent_script",
        parameter_overrides=[
            Parameter("script_durations_s", value=[0.5, 0.25]),
            Parameter("script_linear_x", value=[0.4, 0.0]),
            Parameter("script_linear_y", value=[0.0, 0.0]),
            Parameter("script_angular_z", value=[0.0, 0.8]),
        ],
    )
    client = _client_node("mock_agent_driver")
    executor = SingleThreadedExecutor()
    commands: list[Twist] = []
    task_states: list[AgentTaskState] = []
    try:
        reset_client = client.create_client(ResetAgent, "/roboharness/agent/reset_episode")
        state_publisher = client.create_publisher(
            EpisodeState, "/roboharness/episode/state", latched_control_qos()
        )
        task_publisher = client.create_publisher(
            PointNavTask, "/roboharness/task/pointnav", latched_control_qos()
        )
        clock_publisher = client.create_publisher(Clock, "/clock", 1)
        client.create_subscription(Twist, "/robot/cmd_vel", commands.append, command_qos())
        client.create_subscription(
            AgentTaskState,
            "/roboharness/agent/task_state",
            task_states.append,
            latched_control_qos(),
        )
        executor.add_node(agent)
        executor.add_node(client)
        _spin_until(
            executor,
            lambda: state_publisher.get_subscription_count() > 0
            and task_publisher.get_subscription_count() > 0
            and clock_publisher.get_subscription_count() > 0,
        )

        assert _call_reset(executor, reset_client, _reset_request()).success
        _spin_until(
            executor,
            lambda: commands
            and _is_zero(commands[-1])
            and task_states
            and task_states[-1].state == AgentTaskState.IDLE,
        )
        assert task_states[-1].sequence == 0

        state_publisher.publish(_episode_state(EpisodeState.RUNNING, 0))
        _spin_until(
            executor,
            lambda: task_states[-1].state == AgentTaskState.RUNNING,
        )
        assert task_states[-1].sequence == 1
        task_publisher.publish(_task(episode_id="other"))
        clock_publisher.publish(_clock(10_000_000_000))
        _spin_for(executor, 0.1)
        assert _is_zero(commands[-1])

        task_publisher.publish(_task())
        _spin_until(executor, lambda: commands[-1].linear.x == pytest.approx(0.4))
        clock_publisher.publish(_clock(10_000_000_000))
        _spin_for(executor, 0.05)
        clock_publisher.publish(_clock(10_500_000_000))
        _spin_until(executor, lambda: commands[-1].angular.z == pytest.approx(0.8))
        clock_publisher.publish(_clock(10_750_000_000))
        _spin_until(executor, lambda: _is_zero(commands[-1]))

        state_publisher.publish(_episode_state(EpisodeState.FINISHED, 1))
        _spin_until(
            executor,
            lambda: _is_zero(commands[-1])
            and task_states[-1].state == AgentTaskState.IDLE,
        )
        assert task_states[-1].sequence == 2
        state_publisher.publish(_episode_state(EpisodeState.RUNNING, 0))
        clock_publisher.publish(_clock(11_000_000_000))
        _spin_for(executor, 0.1)
        assert _is_zero(commands[-1])
    finally:
        executor.shutdown()
        agent.destroy_node()
        client.destroy_node()


def test_duplicate_reset_does_not_restart_and_new_episode_does_not_leak_state(
    ros_context: None,
) -> None:
    agent = MockAgentNode(
        node_name="mock_agent_isolation",
        parameter_overrides=[
            Parameter("script_durations_s", value=[0.5]),
            Parameter("script_linear_x", value=[0.5]),
            Parameter("script_linear_y", value=[0.0]),
            Parameter("script_angular_z", value=[0.0]),
        ],
    )
    client = _client_node("mock_agent_isolation_driver")
    executor = SingleThreadedExecutor()
    commands: list[Twist] = []
    try:
        reset_client = client.create_client(ResetAgent, "/roboharness/agent/reset_episode")
        state_publisher = client.create_publisher(
            EpisodeState, "/roboharness/episode/state", latched_control_qos()
        )
        task_publisher = client.create_publisher(
            PointNavTask, "/roboharness/task/pointnav", latched_control_qos()
        )
        clock_publisher = client.create_publisher(Clock, "/clock", 1)
        client.create_subscription(Twist, "/robot/cmd_vel", commands.append, command_qos())
        executor.add_node(agent)
        executor.add_node(client)
        _spin_until(executor, lambda: task_publisher.get_subscription_count() > 0)

        request = _reset_request()
        assert _call_reset(executor, reset_client, request).success
        task_publisher.publish(_task())
        state_publisher.publish(_episode_state(EpisodeState.RUNNING, 0))
        clock_publisher.publish(_clock(1_000_000_000))
        _spin_for(executor, 0.05)
        clock_publisher.publish(_clock(1_500_000_000))
        _spin_until(executor, lambda: commands and _is_zero(commands[-1]))

        assert _call_reset(executor, reset_client, request).success
        clock_publisher.publish(_clock(1_600_000_000))
        _spin_for(executor, 0.1)
        assert _is_zero(commands[-1])

        conflict = _call_reset(
            executor,
            reset_client,
            _reset_request(request_id="reset-1", episode_id="episode-2"),
        )
        assert not conflict.success
        assert conflict.error_code == RESET_ID_CONFLICT

        assert _call_reset(
            executor,
            reset_client,
            _reset_request(request_id="reset-2", episode_id="episode-2"),
        ).success
        clock_publisher.publish(_clock(2_000_000_000))
        _spin_for(executor, 0.1)
        assert _is_zero(commands[-1])
        task_publisher.publish(_task(episode_id="episode-2"))
        state_publisher.publish(
            _episode_state(EpisodeState.RUNNING, 0, episode_id="episode-2")
        )
        _spin_until(executor, lambda: commands[-1].linear.x == pytest.approx(0.5))
    finally:
        executor.shutdown()
        agent.destroy_node()
        client.destroy_node()


def test_reset_failure_error_and_stale_status_are_injectable(
    ros_context: None,
) -> None:
    agent = MockAgentNode(
        node_name="mock_agent_faults",
        parameter_overrides=[
            Parameter("reset_failure", value=True),
            Parameter("suppress_status_heartbeat", value=True),
        ],
    )
    client = _client_node("mock_agent_fault_observer")
    executor = SingleThreadedExecutor()
    commands: list[Twist] = []
    try:
        status = StatusMonitor(client, "/roboharness/agent/status", stale_timeout_s=0.2)
        reset_client = client.create_client(ResetAgent, "/roboharness/agent/reset_episode")
        clock_publisher = client.create_publisher(Clock, "/clock", 1)
        client.create_subscription(Twist, "/robot/cmd_vel", commands.append, command_qos())
        executor.add_node(agent)
        executor.add_node(client)
        _spin_until(executor, lambda: status.tracker.latest("mock_agent") is not None)

        response = _call_reset(executor, reset_client, _reset_request())
        assert not response.success
        _spin_until(
            executor,
            lambda: status.tracker.latest("mock_agent").state == ComponentStatus.ERROR
            and commands
            and _is_zero(commands[-1]),
        )
        _spin_for(executor, 0.25)
        assert status.tracker.is_stale("mock_agent")

        immutable = agent.set_parameters(
            [Parameter("script_durations_s", value=[10.0])]
        )
        assert not immutable[0].successful
        agent.set_parameters([Parameter("inject_error", value=True)])
        clock_publisher.publish(_clock(1))
        _spin_until(
            executor,
            lambda: status.tracker.latest("mock_agent").error_code != 0,
        )
    finally:
        executor.shutdown()
        agent.destroy_node()
        client.destroy_node()


def test_executable_crash_fault_exits_nonzero() -> None:
    environment = os.environ.copy()
    environment["ROS_DOMAIN_ID"] = str(100 + os.getpid() % 100)
    result = subprocess.run(
        [
            "ros2",
            "run",
            "rh_mock_agent",
            "mock_agent",
            "--ros-args",
            "-p",
            "crash_after_s:=0.05",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
        env=environment,
    )

    assert result.returncode != 0
    assert "injected mock agent crash" in result.stderr
