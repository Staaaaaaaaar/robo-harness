from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import ComponentStatus, EpisodeState
from rh_interfaces.srv import AbortEpisode, ResetAgent, ResetEnv, StartEpisode

from rh_core import (
    ExecutionMode,
    ExperimentConfig,
    ExperimentState,
    TerminationReason,
    parse_experiment_config,
)
from rh_experiment.controller import ControlDecision
from rh_experiment.orchestrator import SingleEpisodeOrchestratorNode
from rh_ros import StatusPublisher, latched_control_qos


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _config(mode: ExecutionMode = ExecutionMode.MANUAL) -> ExperimentConfig:
    return parse_experiment_config(
        {
            "schema_version": 1,
            "experiment": {
                "name": "experiment-1",
                "execution_mode": mode.value,
                "episodes": [
                    {
                        "episode_id": "episode-1",
                        "scenario": "stub-world",
                        "initial_pose": {
                            "frame_id": "map",
                            "x": 1.0,
                            "y": 2.0,
                            "z": 0.4,
                            "roll": 0.1,
                            "pitch": -0.2,
                            "yaw": 0.3,
                        },
                        "task": {
                            "type": "pointnav",
                            "goal": {
                                "frame_id": "map",
                                "x": 4.0,
                                "y": 5.0,
                                "z": 0.4,
                            },
                            "success_radius_m": 0.5,
                            "timeout_s": 30.0,
                        },
                        "seed": 42,
                    }
                ],
            },
        }
    )


class _StubComponent(Node):
    def __init__(
        self,
        role: str,
        reset_order: list[str],
        *,
        ready: bool = True,
        reset_delay_s: float = 0.0,
        reset_success: bool = True,
    ) -> None:
        super().__init__(f"stub_{role}_{uuid4().hex}")
        self.role = role
        self.reset_order = reset_order
        self.reset_delay_s = reset_delay_s
        self.reset_success = reset_success
        self.states: list[EpisodeState] = []
        self.status = StatusPublisher(
            self,
            f"/roboharness/{role}/status",
            role,
            heartbeat_period_s=0.05,
        )
        self.create_subscription(
            EpisodeState,
            "/roboharness/episode/state",
            self.states.append,
            latched_control_qos(),
        )
        if role == "env":
            self.create_service(
                ResetEnv,
                "/roboharness/env/reset_episode",
                self._reset_env,
            )
        else:
            self.create_service(
                ResetAgent,
                "/roboharness/agent/reset_episode",
                self._reset_agent,
            )
        if ready:
            self.status.transition(ComponentStatus.READY, detail=f"{role} ready")

    def _record_reset(self) -> tuple[bool, int, str]:
        self.reset_order.append(self.role)
        if self.reset_delay_s:
            time.sleep(self.reset_delay_s)
        if self.reset_success:
            return True, 0, ""
        return False, 9001, f"{self.role} injected reset rejection"

    def _reset_env(
        self, request: ResetEnv.Request, response: ResetEnv.Response
    ) -> ResetEnv.Response:
        assert request.experiment_id == "experiment-1"
        assert request.episode_id == "episode-1"
        assert request.initial_pose.header.frame_id == "map"
        assert request.initial_pose.pose.position.z == pytest.approx(0.4)
        response.success, response.error_code, response.detail = self._record_reset()
        return response

    def _reset_agent(
        self, request: ResetAgent.Request, response: ResetAgent.Response
    ) -> ResetAgent.Response:
        assert request.experiment_id == "experiment-1"
        assert request.episode_id == "episode-1"
        response.success, response.error_code, response.detail = self._record_reset()
        return response


@dataclass
class _Graph:
    env: _StubComponent
    agent: _StubComponent
    orchestrator: SingleEpisodeOrchestratorNode
    client: Node
    executor: MultiThreadedExecutor
    spin_thread: threading.Thread

    def shutdown(self) -> None:
        self.orchestrator.destroy_node()
        self.executor.shutdown(timeout_sec=2.0)
        self.spin_thread.join(timeout=2.0)
        self.env.destroy_node()
        self.agent.destroy_node()
        self.client.destroy_node()


def _start_graph(
    *,
    mode: ExecutionMode = ExecutionMode.MANUAL,
    env_ready: bool = True,
    agent_ready: bool = True,
    env_reset_delay_s: float = 0.0,
    env_reset_success: bool = True,
    startup_timeout_s: float = 1.0,
    status_stale_timeout_s: float = 0.3,
    reset_timeout_s: float = 0.2,
) -> tuple[_Graph, list[str]]:
    reset_order: list[str] = []
    env = _StubComponent(
        "env",
        reset_order,
        ready=env_ready,
        reset_delay_s=env_reset_delay_s,
        reset_success=env_reset_success,
    )
    agent = _StubComponent("agent", reset_order, ready=agent_ready)
    orchestrator = SingleEpisodeOrchestratorNode(
        node_name=f"orchestrator_{uuid4().hex}",
        config=_config(mode),
        parameter_overrides=[
            Parameter("startup_timeout_s", value=startup_timeout_s),
            Parameter("status_stale_timeout_s", value=status_stale_timeout_s),
            Parameter("reset_timeout_s", value=reset_timeout_s),
            Parameter("safe_stop_timeout_s", value=0.2),
            Parameter("control_request_timeout_s", value=0.5),
        ],
    )
    client = rclpy.create_node(f"orchestrator_client_{uuid4().hex}")
    executor = MultiThreadedExecutor(num_threads=8)
    for node in (env, agent, orchestrator, client):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    return _Graph(env, agent, orchestrator, client, executor, spin_thread), reset_order


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _state(orchestrator: SingleEpisodeOrchestratorNode) -> int:
    return orchestrator.state_history[-1].state


def _call(client: Node, service_type: type, topic: str, request: object) -> object:
    service_client = client.create_client(service_type, topic)
    assert service_client.wait_for_service(timeout_sec=1.0)
    future = service_client.call_async(request)
    _wait_until(future.done)
    result = future.result()
    assert result is not None
    return result


def _start_request(
    *, experiment_id: str = "experiment-1", episode_id: str = "episode-1"
) -> StartEpisode.Request:
    request = StartEpisode.Request()
    request.experiment_id = experiment_id
    request.episode_id = episode_id
    return request


def _abort_request(reason: str = "operator request") -> AbortEpisode.Request:
    request = AbortEpisode.Request()
    request.experiment_id = "experiment-1"
    request.episode_id = "episode-1"
    request.reason = reason
    return request


def test_manual_happy_path_resets_in_order_and_safe_stops(
    ros_context: None,
) -> None:
    graph, reset_order = _start_graph()
    try:
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.READY)
        assert reset_order == ["env", "agent"]

        start = _call(
            graph.client,
            StartEpisode,
            "/roboharness/episode/start",
            _start_request(),
        )
        assert start.accepted
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.RUNNING)

        abort = _call(
            graph.client,
            AbortEpisode,
            "/roboharness/episode/abort",
            _abort_request(),
        )
        assert abort.accepted
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.FINISHED)

        transitions = []
        for message in graph.orchestrator.state_history:
            if not transitions or message.state != transitions[-1]:
                transitions.append(message.state)
        assert transitions == [
            EpisodeState.PREPARING,
            EpisodeState.READY,
            EpisodeState.RUNNING,
            EpisodeState.TERMINATING,
            EpisodeState.FINISHED,
        ]
        final = graph.orchestrator.state_history[-1]
        assert final.termination_reason == EpisodeState.ABORTED
        assert final.sequence == 4
        assert graph.orchestrator.experiment_state is ExperimentState.FINISHED
        assert graph.env.states and graph.agent.states
    finally:
        graph.shutdown()


def test_illegal_start_is_rejected_while_preparing(ros_context: None) -> None:
    graph, reset_order = _start_graph(env_ready=False, startup_timeout_s=1.0)
    try:
        start = _call(
            graph.client,
            StartEpisode,
            "/roboharness/episode/start",
            _start_request(),
        )
        assert not start.accepted
        assert "PREPARING" in start.detail
        assert reset_order == []
    finally:
        graph.shutdown()


def test_stale_component_commits_one_env_error(ros_context: None) -> None:
    graph, _ = _start_graph(status_stale_timeout_s=0.15)
    try:
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.READY)
        graph.env.status.set_heartbeat_enabled(False)
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.FINISHED)

        final = graph.orchestrator.state_history[-1]
        assert final.termination_reason == EpisodeState.ENV_ERROR
        assert graph.orchestrator.experiment_state is ExperimentState.FAILED
        assert sum(
            message.state == EpisodeState.TERMINATING
            for message in graph.orchestrator.state_history
        ) >= 1
    finally:
        graph.shutdown()


def test_reset_timeout_finishes_with_env_error_before_agent_reset(
    ros_context: None,
) -> None:
    graph, reset_order = _start_graph(
        env_reset_delay_s=0.3,
        reset_timeout_s=0.05,
    )
    try:
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.FINISHED)
        final = graph.orchestrator.state_history[-1]
        assert final.termination_reason == EpisodeState.ENV_ERROR
        assert reset_order == ["env"]
        assert graph.orchestrator.experiment_state is ExperimentState.FAILED
    finally:
        graph.shutdown()


def test_termination_reason_is_committed_once(ros_context: None) -> None:
    graph, _ = _start_graph(mode=ExecutionMode.AUTOMATIC)
    try:
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.RUNNING)
        first = graph.orchestrator.submit_termination(
            TerminationReason.SUCCESS,
            detail="goal reached",
        )
        second = graph.orchestrator.submit_termination(
            TerminationReason.TIMEOUT,
            detail="late timeout",
        )
        assert first == ControlDecision(True, "goal reached")
        assert not second.accepted
        _wait_until(lambda: _state(graph.orchestrator) == EpisodeState.FINISHED)

        abort = _call(
            graph.client,
            AbortEpisode,
            "/roboharness/episode/abort",
            _abort_request(),
        )
        assert not abort.accepted
        assert (
            graph.orchestrator.state_history[-1].termination_reason
            == EpisodeState.SUCCESS
        )
    finally:
        graph.shutdown()
