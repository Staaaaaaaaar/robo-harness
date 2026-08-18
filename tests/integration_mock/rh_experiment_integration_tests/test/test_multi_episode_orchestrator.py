from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import ComponentStatus, EpisodeResult
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rh_interfaces.srv import ResetAgent, ResetEnv

from rh_core import EpisodeSpec, TerminationReason, parse_experiment_config
from rh_eval_simple_navigation import SimpleNavigationObserver
from rh_experiment import (
    ControlDecision,
    EpisodeEvaluationResult,
    EpisodeMetrics,
    ResultRecorder,
    TrajectoryPoint,
    validate_result_tree,
)
from rh_experiment.orchestrator import ExperimentOrchestratorNode
from rh_mock_agent.node import MockAgentNode
from rh_mock_env.node import MockEnvironmentNode
from rh_pointnav import PointNavTaskPublisher
from rh_ros import StatusPublisher, latched_control_qos


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _config(episode_count: int = 3, *, timeout_s: float = 10.0):
    return parse_experiment_config(
        {
            "schema_version": 1,
            "experiment": {
                "name": "multi-experiment",
                "execution_mode": "automatic",
                "episodes": [
                    {
                        "episode_id": f"episode-{index}",
                        "scenario": "stub-world",
                        "initial_pose": {
                            "frame_id": "map",
                            "x": float(index),
                            "y": 0.0,
                            "z": 0.4,
                            "roll": 0.0,
                            "pitch": 0.0,
                            "yaw": 0.0,
                        },
                        "task": {
                            "type": "pointnav",
                            "goal": {
                                "frame_id": "map",
                                "x": float(index + 1),
                                "y": 0.0,
                                "z": 0.4,
                            },
                            "success_radius_m": 0.5,
                            "timeout_s": timeout_s,
                        },
                        "seed": index,
                    }
                    for index in range(episode_count)
                ],
            },
        }
    )


class _Component(Node):
    def __init__(self, role: str, *, fail_episode: str | None = None) -> None:
        super().__init__(f"multi_{role}_{uuid4().hex}")
        self.role = role
        self.fail_episode = fail_episode
        self.reset_ids: list[str] = []
        self.states: list[tuple[str, int]] = []
        self.status = StatusPublisher(
            self,
            f"/roboharness/{role}/status",
            role,
            heartbeat_period_s=0.05,
        )
        self.create_subscription(
            EpisodeStateMessage,
            "/roboharness/episode/state",
            lambda message: self.states.append((message.episode_id, message.state)),
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
        self.status.transition(ComponentStatus.READY, detail=f"{role} ready")

    def _outcome(self, episode_id: str) -> tuple[bool, int, str]:
        self.reset_ids.append(episode_id)
        if episode_id == self.fail_episode:
            return False, 9001, f"injected {self.role} reset failure"
        return True, 0, ""

    def _reset_env(
        self,
        request: ResetEnv.Request,
        response: ResetEnv.Response,
    ) -> ResetEnv.Response:
        response.success, response.error_code, response.detail = self._outcome(
            request.episode_id
        )
        return response

    def _reset_agent(
        self,
        request: ResetAgent.Request,
        response: ResetAgent.Response,
    ) -> ResetAgent.Response:
        response.success, response.error_code, response.detail = self._outcome(
            request.episode_id
        )
        return response


class _TaskPublisher:
    def __init__(self, episode_id: str, publications: list[str]) -> None:
        self.episode_id = episode_id
        self.publications = publications
        self.closed = False

    def publish(self) -> None:
        self.publications.append(self.episode_id)

    def close(self) -> None:
        self.closed = True


class _Evaluator:
    def __init__(
        self,
        episode_id: str,
        submit: Callable[..., ControlDecision],
    ) -> None:
        self.episode_id = episode_id
        self.submit = submit
        self.closed = False

    def finalize(
        self,
        reason: TerminationReason,
        simulation_time_s: float,
    ) -> EpisodeEvaluationResult:
        return EpisodeEvaluationResult(
            metrics=EpisodeMetrics(
                success=reason is TerminationReason.SUCCESS,
                elapsed_time_s=1.0,
                path_length_m=0.0,
                final_distance_to_goal_m=0.0,
                timeout=reason is TerminationReason.TIMEOUT,
                termination_reason=reason,
                sample_count=1,
            ),
            trajectory=(TrajectoryPoint(0.0, "map", 0.0, 0.0, 0.4),),
        )

    def close(self) -> None:
        self.closed = True


class _Graph:
    def __init__(
        self,
        tmp_path: Path,
        *,
        env_fail_episode: str | None = None,
        invalid_episode: str | None = None,
    ) -> None:
        self.config = _config()
        self.env = _Component("env", fail_episode=env_fail_episode)
        self.agent = _Component("agent")
        self.client = rclpy.create_node(f"multi_client_{uuid4().hex}")
        self.results: list[EpisodeResult] = []
        self.client.create_subscription(
            EpisodeResult,
            "/roboharness/episode/result",
            self.results.append,
            10,
        )
        self.publications: list[str] = []
        self.evaluators: list[_Evaluator] = []

        def task_factory(
            node: Node,
            experiment_id: str,
            episode: EpisodeSpec,
        ) -> _TaskPublisher:
            del node, experiment_id
            if episode.episode_id == invalid_episode:
                raise ValueError("injected invalid task")
            return _TaskPublisher(episode.episode_id, self.publications)

        def evaluator_factory(
            node: Node,
            experiment_id: str,
            episode: EpisodeSpec,
            submit: Callable[..., ControlDecision],
        ) -> _Evaluator:
            del node, experiment_id
            evaluator = _Evaluator(episode.episode_id, submit)
            self.evaluators.append(evaluator)
            return evaluator

        recorder = ResultRecorder(
            tmp_path,
            "multi-experiment",
            self.config,
        )
        self.orchestrator = ExperimentOrchestratorNode(
            node_name=f"multi_orchestrator_{uuid4().hex}",
            config=self.config,
            task_publisher_factory=task_factory,
            evaluator_factory=evaluator_factory,
            recorder=recorder,
            parameter_overrides=[
                Parameter("startup_timeout_s", value=1.0),
                Parameter("status_stale_timeout_s", value=0.5),
                Parameter("reset_timeout_s", value=0.3),
                Parameter("safe_stop_timeout_s", value=0.2),
                Parameter("control_request_timeout_s", value=0.5),
            ],
        )
        self.result_directory = recorder.experiment_directory
        self.executor = MultiThreadedExecutor(num_threads=8)
        for node in (self.env, self.agent, self.orchestrator, self.client):
            self.executor.add_node(node)
        self.spin_thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.spin_thread.start()

    def shutdown(self) -> None:
        self.orchestrator.destroy_node()
        self.executor.shutdown(timeout_sec=2.0)
        self.spin_thread.join(timeout=2.0)
        self.env.destroy_node()
        self.agent.destroy_node()
        self.client.destroy_node()


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _is_state(
    orchestrator: ExperimentOrchestratorNode,
    episode_id: str,
    state: int,
) -> bool:
    history = orchestrator.state_history
    return bool(
        history
        and history[-1].episode_id == episode_id
        and history[-1].state == state
    )


def test_three_episodes_reuse_components_and_commit_independent_results(
    ros_context: None,
    tmp_path: Path,
) -> None:
    process_id = os.getpid()
    graph = _Graph(tmp_path)
    try:
        reasons = (
            TerminationReason.SUCCESS,
            TerminationReason.TIMEOUT,
            TerminationReason.ABORTED,
        )
        stale_submitter: Callable[..., ControlDecision] | None = None
        for index, reason in enumerate(reasons):
            episode_id = f"episode-{index}"
            _wait_until(
                lambda episode_id=episode_id: _is_state(
                    graph.orchestrator,
                    episode_id,
                    EpisodeStateMessage.RUNNING,
                )
            )
            if index == 0:
                stale_submitter = graph.evaluators[0].submit
            if index == 1:
                assert stale_submitter is not None
                stale = stale_submitter(
                    TerminationReason.FAILURE,
                    detail="late Episode 0 callback",
                )
                assert not stale.accepted
                assert _is_state(
                    graph.orchestrator,
                    episode_id,
                    EpisodeStateMessage.RUNNING,
                )
            decision = graph.orchestrator.submit_termination(
                reason,
                detail=f"finish {episode_id}",
            )
            assert decision.accepted

        _wait_until(lambda: graph.orchestrator.experiment_state.name == "FINISHED")
        _wait_until(lambda: len(graph.results) == 3)

        assert os.getpid() == process_id
        assert graph.env.reset_ids == ["episode-0", "episode-1", "episode-2"]
        assert graph.agent.reset_ids == graph.env.reset_ids
        assert graph.publications == graph.env.reset_ids
        assert all(evaluator.closed for evaluator in graph.evaluators)
        assert [message.termination_reason for message in graph.results] == [
            int(reason) for reason in reasons
        ]

        result = validate_result_tree(graph.result_directory)
        assert result.metadata["complete"] is True
        assert [episode.episode_id for episode in result.episodes] == graph.env.reset_ids
        assert result.summary["completed_episode_count"] == 3
        assert result.summary["counts"]["SUCCESS"] == 1
        assert result.summary["counts"]["TIMEOUT"] == 1
        assert result.summary["counts"]["ABORTED"] == 1
    finally:
        graph.shutdown()


def test_invalid_task_continues_but_reset_failure_stops_experiment(
    ros_context: None,
    tmp_path: Path,
) -> None:
    invalid_graph = _Graph(tmp_path / "invalid", invalid_episode="episode-1")
    try:
        _wait_until(
            lambda: _is_state(
                invalid_graph.orchestrator,
                "episode-0",
                EpisodeStateMessage.RUNNING,
            )
        )
        assert invalid_graph.orchestrator.submit_termination(
            TerminationReason.SUCCESS,
            detail="first complete",
        ).accepted
        _wait_until(
            lambda: _is_state(
                invalid_graph.orchestrator,
                "episode-2",
                EpisodeStateMessage.RUNNING,
            )
        )
        assert invalid_graph.orchestrator.submit_termination(
            TerminationReason.SUCCESS,
            detail="last complete",
        ).accepted
        _wait_until(
            lambda: invalid_graph.orchestrator.experiment_state.name == "FINISHED"
        )
        validated = validate_result_tree(invalid_graph.result_directory)
        assert [
            episode.metrics["termination_reason"] for episode in validated.episodes
        ] == ["SUCCESS", "INVALID_TASK", "SUCCESS"]
    finally:
        invalid_graph.shutdown()

    failed_graph = _Graph(tmp_path / "reset", env_fail_episode="episode-1")
    try:
        _wait_until(
            lambda: _is_state(
                failed_graph.orchestrator,
                "episode-0",
                EpisodeStateMessage.RUNNING,
            )
        )
        assert failed_graph.orchestrator.submit_termination(
            TerminationReason.SUCCESS,
            detail="first complete",
        ).accepted
        _wait_until(
            lambda: _is_state(
                failed_graph.orchestrator,
                "episode-1",
                EpisodeStateMessage.FINISHED,
            )
        )
        assert failed_graph.orchestrator.experiment_state.name == "FAILED"
        assert failed_graph.env.reset_ids == ["episode-0", "episode-1"]
        assert failed_graph.agent.reset_ids == ["episode-0"]
        assert "episode-2" not in {
            message.episode_id for message in failed_graph.orchestrator.state_history
        }
        validated = validate_result_tree(failed_graph.result_directory)
        assert validated.metadata["complete"] is False
        assert [episode.episode_id for episode in validated.episodes] == [
            "episode-0",
            "episode-1",
        ]
    finally:
        failed_graph.shutdown()


def test_reference_mock_vertical_slice_runs_three_timeouts_without_restart(
    ros_context: None,
    tmp_path: Path,
) -> None:
    config = _config(timeout_s=0.25)
    env = MockEnvironmentNode(node_name=f"vertical_env_{uuid4().hex}")
    agent = MockAgentNode(node_name=f"vertical_agent_{uuid4().hex}")

    def task_factory(
        node: Node,
        experiment_id: str,
        episode: EpisodeSpec,
    ) -> PointNavTaskPublisher:
        return PointNavTaskPublisher(node, experiment_id, episode)

    def evaluator_factory(
        node: Node,
        experiment_id: str,
        episode: EpisodeSpec,
        submit: Callable[..., ControlDecision],
    ) -> SimpleNavigationObserver:
        return SimpleNavigationObserver(node, experiment_id, episode, submit)

    orchestrator = ExperimentOrchestratorNode(
        node_name=f"vertical_orchestrator_{uuid4().hex}",
        config=config,
        task_publisher_factory=task_factory,
        evaluator_factory=evaluator_factory,
        parameter_overrides=[
            Parameter("results_root", value=str(tmp_path)),
            Parameter("env_component_id", value="mock_env"),
            Parameter("agent_component_id", value="mock_agent"),
            Parameter("startup_timeout_s", value=2.0),
            Parameter("status_stale_timeout_s", value=2.0),
            Parameter("reset_timeout_s", value=1.0),
            Parameter("safe_stop_timeout_s", value=0.5),
            Parameter("simulation_clock_stale_timeout_s", value=1.0),
        ],
    )
    process_id = os.getpid()
    executor = MultiThreadedExecutor(num_threads=10)
    for node in (env, agent, orchestrator):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        _wait_until(
            lambda: orchestrator.experiment_state.name == "FINISHED",
            timeout_s=10.0,
        )

        assert os.getpid() == process_id
        validated = validate_result_tree(tmp_path / "multi-experiment")
        assert validated.metadata["complete"] is True
        assert validated.summary["episode_count"] == 3
        assert validated.summary["counts"]["TIMEOUT"] == 3
        assert all(
            episode.metrics["sample_count"] > 0 for episode in validated.episodes
        )
    finally:
        orchestrator.destroy_node()
        executor.shutdown(timeout_sec=2.0)
        spin_thread.join(timeout=2.0)
        env.destroy_node()
        agent.destroy_node()
