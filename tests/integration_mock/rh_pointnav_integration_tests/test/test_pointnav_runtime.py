from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import ComponentStatus, EpisodeState, PointNavTask
from rh_interfaces.srv import ResetAgent, ResetEnv

from rh_core import EpisodeSpec, ExecutionMode, ExperimentConfig, parse_experiment_config
from rh_experiment.orchestrator import SingleEpisodeOrchestratorNode
from rh_pointnav.publisher import PointNavTaskPublisher
from rh_ros import StatusPublisher, latched_control_qos


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _config() -> ExperimentConfig:
    return parse_experiment_config(
        {
            "schema_version": 1,
            "experiment": {
                "name": "experiment-1",
                "execution_mode": ExecutionMode.MANUAL.value,
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
                                "z": 1.0,
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


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _spin_until(
    executor: SingleThreadedExecutor,
    predicate: Callable[[], bool],
    timeout_s: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert predicate()


def _snapshot(message: PointNavTask) -> tuple[object, ...]:
    return (
        message.experiment_id,
        message.episode_id,
        message.goal.header.frame_id,
        message.goal.point.x,
        message.goal.point.y,
        message.goal.point.z,
        message.success_radius_m,
        message.timeout_s,
        message.seed,
    )


def test_env_agent_and_evaluator_late_joiners_receive_identical_snapshot(
    ros_context: None,
) -> None:
    config = _config()
    publisher_node = rclpy.create_node(f"pointnav_publisher_{uuid4().hex}")
    publisher = PointNavTaskPublisher(
        publisher_node,
        "experiment-1",
        config.experiment.episodes[0],
    )
    publisher.publish()

    consumers = [rclpy.create_node(f"task_consumer_{uuid4().hex}") for _ in range(3)]
    received: list[list[PointNavTask]] = [[], [], []]
    executor = SingleThreadedExecutor()
    try:
        executor.add_node(publisher_node)
        for node, messages in zip(consumers, received, strict=True):
            node.create_subscription(
                PointNavTask,
                "/roboharness/task/pointnav",
                messages.append,
                latched_control_qos(),
            )
            executor.add_node(node)
        _spin_until(executor, lambda: all(received))

        snapshots = [_snapshot(messages[-1]) for messages in received]
        assert snapshots[0] == snapshots[1] == snapshots[2]
        assert snapshots[0] == (
            "experiment-1",
            "episode-1",
            "map",
            4.0,
            5.0,
            1.0,
            0.5,
            30.0,
            42,
        )
        assert not hasattr(received[0][-1].goal, "pose")
    finally:
        executor.shutdown()
        publisher_node.destroy_node()
        for node in consumers:
            node.destroy_node()


class _ComponentStub(Node):
    def __init__(self, role: str, reset_order: list[str]) -> None:
        super().__init__(f"pointnav_{role}_{uuid4().hex}")
        self.role = role
        self.reset_order = reset_order
        self.tasks: list[PointNavTask] = []
        self.states: list[EpisodeState] = []
        self.status = StatusPublisher(
            self,
            f"/roboharness/{role}/status",
            role,
            heartbeat_period_s=0.05,
        )
        self.create_subscription(
            PointNavTask,
            "/roboharness/task/pointnav",
            self.tasks.append,
            latched_control_qos(),
        )
        self.create_subscription(
            EpisodeState,
            "/roboharness/episode/state",
            self.states.append,
            latched_control_qos(),
        )
        if role == "env":
            self.create_service(ResetEnv, "/roboharness/env/reset_episode", self._env_reset)
        else:
            self.create_service(
                ResetAgent,
                "/roboharness/agent/reset_episode",
                self._agent_reset,
            )
        self.status.transition(ComponentStatus.READY, detail=f"{role} ready")

    def _env_reset(
        self, request: ResetEnv.Request, response: ResetEnv.Response
    ) -> ResetEnv.Response:
        self.reset_order.append(self.role)
        response.success = True
        return response

    def _agent_reset(
        self, request: ResetAgent.Request, response: ResetAgent.Response
    ) -> ResetAgent.Response:
        self.reset_order.append(self.role)
        response.success = True
        return response


def test_orchestrator_publishes_task_after_resets_and_before_ready(
    ros_context: None,
) -> None:
    config = _config()
    reset_order: list[str] = []
    env = _ComponentStub("env", reset_order)
    agent = _ComponentStub("agent", reset_order)
    publishers: list[PointNavTaskPublisher] = []

    def factory(
        node: Node,
        experiment_id: str,
        episode: EpisodeSpec,
    ) -> PointNavTaskPublisher:
        publisher = PointNavTaskPublisher(node, experiment_id, episode)
        publishers.append(publisher)
        return publisher

    orchestrator = SingleEpisodeOrchestratorNode(
        node_name=f"pointnav_orchestrator_{uuid4().hex}",
        config=config,
        task_publisher_factory=factory,
        parameter_overrides=[
            Parameter("startup_timeout_s", value=1.0),
            Parameter("status_stale_timeout_s", value=0.3),
            Parameter("reset_timeout_s", value=0.2),
            Parameter("safe_stop_timeout_s", value=0.2),
        ],
    )
    executor = MultiThreadedExecutor(num_threads=6)
    for node in (env, agent, orchestrator):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    evaluator = None
    try:
        _wait_until(
            lambda: orchestrator.state_history[-1].state == EpisodeState.READY
        )
        _wait_until(lambda: bool(env.tasks) and bool(agent.tasks))
        assert reset_order == ["env", "agent"]
        assert publishers[0].publish_count == 1
        assert _snapshot(env.tasks[-1]) == _snapshot(agent.tasks[-1])
        assert env.tasks[-1].episode_id == orchestrator.episode_id

        evaluator = rclpy.create_node(f"late_evaluator_{uuid4().hex}")
        evaluator_tasks: list[PointNavTask] = []
        evaluator.create_subscription(
            PointNavTask,
            "/roboharness/task/pointnav",
            evaluator_tasks.append,
            latched_control_qos(),
        )
        executor.add_node(evaluator)
        _wait_until(lambda: bool(evaluator_tasks))
        assert _snapshot(evaluator_tasks[-1]) == _snapshot(env.tasks[-1])
    finally:
        orchestrator.stop()
        executor.shutdown(timeout_sec=2.0)
        spin_thread.join(timeout=2.0)
        orchestrator.destroy_node()
        env.destroy_node()
        agent.destroy_node()
        if evaluator is not None:
            evaluator.destroy_node()
