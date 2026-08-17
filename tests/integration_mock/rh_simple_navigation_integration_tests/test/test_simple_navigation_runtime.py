from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import AgentTaskState, ComponentStatus, EpisodeState
from rh_interfaces.srv import ResetAgent, ResetEnv
from rosgraph_msgs.msg import Clock
from tf2_ros import StaticTransformBroadcaster

from rh_core import (
    EpisodeSpec,
    ExecutionMode,
    ExperimentConfig,
    parse_experiment_config,
)
from rh_eval_simple_navigation import SimpleNavigationObserver
from rh_experiment import TerminationSubmitter
from rh_experiment.orchestrator import SingleEpisodeOrchestratorNode
from rh_pointnav import PointNavTaskPublisher
from rh_ros import StatusPublisher, latched_control_qos, sensor_qos


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _config(mode: ExecutionMode = ExecutionMode.AUTOMATIC) -> ExperimentConfig:
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
                            "x": 0.0,
                            "y": 0.0,
                            "z": 0.0,
                            "roll": 0.0,
                            "pitch": 0.0,
                            "yaw": 0.0,
                        },
                        "task": {
                            "type": "pointnav",
                            "goal": {
                                "frame_id": "map",
                                "x": 3.0,
                                "y": 4.0,
                                "z": 0.0,
                            },
                            "success_radius_m": 0.25,
                            "timeout_s": 5.0,
                        },
                        "seed": 42,
                    }
                ],
            },
        }
    )


class _ComponentStub(Node):
    def __init__(self, role: str, *, ready: bool = True) -> None:
        super().__init__(f"simple_eval_{role}_{uuid4().hex}")
        self.status = StatusPublisher(
            self,
            f"/roboharness/{role}/status",
            role,
            heartbeat_period_s=0.05,
        )
        self.create_subscription(
            EpisodeState,
            "/roboharness/episode/state",
            lambda message: None,
            1,
        )
        self.task_state_publisher = None
        if role == "env":
            self.create_service(
                ResetEnv,
                "/roboharness/env/reset_episode",
                self._reset_env,
            )
        else:
            self.task_state_publisher = self.create_publisher(
                AgentTaskState,
                "/roboharness/agent/task_state",
                latched_control_qos(),
            )
            self.create_service(
                ResetAgent,
                "/roboharness/agent/reset_episode",
                self._reset_agent,
            )
        if ready:
            self.mark_ready()

    def mark_ready(self) -> None:
        self.status.transition(ComponentStatus.READY, detail=f"{self.get_name()} ready")

    def publish_task_state(
        self,
        state: int,
        nanoseconds: int,
        *,
        sequence: int,
    ) -> None:
        assert self.task_state_publisher is not None
        message = AgentTaskState()
        message.stamp.sec, message.stamp.nanosec = divmod(
            nanoseconds,
            1_000_000_000,
        )
        message.experiment_id = "experiment-1"
        message.episode_id = "episode-1"
        message.sequence = sequence
        message.state = state
        message.detail = "integration test navigation state"
        self.task_state_publisher.publish(message)

    @staticmethod
    def _reset_env(
        request: ResetEnv.Request,
        response: ResetEnv.Response,
    ) -> ResetEnv.Response:
        response.success = True
        return response

    @staticmethod
    def _reset_agent(
        request: ResetAgent.Request,
        response: ResetAgent.Response,
    ) -> ResetAgent.Response:
        response.success = True
        return response


def _wait_until(predicate: Callable[[], bool], timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _clock(nanoseconds: int) -> Clock:
    message = Clock()
    message.clock.sec, message.clock.nanosec = divmod(nanoseconds, 1_000_000_000)
    return message


def _odometry(nanoseconds: int, x: float, y: float, z: float) -> Odometry:
    message = Odometry()
    message.header.stamp.sec, message.header.stamp.nanosec = divmod(
        nanoseconds,
        1_000_000_000,
    )
    message.header.frame_id = "odom"
    message.child_frame_id = "base_link"
    message.pose.pose.position.x = x
    message.pose.pose.position.y = y
    message.pose.pose.position.z = z
    message.pose.pose.orientation.w = 1.0
    return message


def _shutdown(
    orchestrator: SingleEpisodeOrchestratorNode,
    executor: MultiThreadedExecutor,
    spin_thread: threading.Thread,
    nodes: tuple[Node, ...],
) -> None:
    orchestrator.stop()
    executor.shutdown(timeout_sec=2.0)
    spin_thread.join(timeout=2.0)
    orchestrator.destroy_node()
    for node in nodes:
        node.destroy_node()


def test_fixed_trajectory_submits_success_to_authoritative_orchestrator(
    ros_context: None,
) -> None:
    config = _config()
    env = _ComponentStub("env", ready=False)
    agent = _ComponentStub("agent", ready=False)
    telemetry = rclpy.create_node(f"simple_eval_telemetry_{uuid4().hex}")
    static_tf_broadcaster = StaticTransformBroadcaster(telemetry)
    map_to_odom = TransformStamped()
    map_to_odom.header.frame_id = "map"
    map_to_odom.child_frame_id = "odom"
    map_to_odom.transform.translation.x = 1.0
    map_to_odom.transform.rotation.w = 1.0
    static_tf_broadcaster.sendTransform(map_to_odom)
    clock_publisher = telemetry.create_publisher(Clock, "/clock", 1)
    odom_publisher = telemetry.create_publisher(
        Odometry,
        "/robot/odom",
        sensor_qos(),
    )
    evaluators: list[SimpleNavigationObserver] = []

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
        submit_termination: TerminationSubmitter,
    ) -> SimpleNavigationObserver:
        evaluator = SimpleNavigationObserver(
            node,
            experiment_id,
            episode,
            submit_termination,
        )
        evaluators.append(evaluator)
        return evaluator

    orchestrator = SingleEpisodeOrchestratorNode(
        node_name=f"simple_eval_orchestrator_{uuid4().hex}",
        config=config,
        task_publisher_factory=task_factory,
        evaluator_factory=evaluator_factory,
        parameter_overrides=[
            Parameter("startup_timeout_s", value=1.0),
            Parameter("status_stale_timeout_s", value=0.5),
            Parameter("reset_timeout_s", value=0.2),
            Parameter("safe_stop_timeout_s", value=0.2),
            Parameter("simulation_clock_stale_timeout_s", value=0.5),
        ],
    )
    executor = MultiThreadedExecutor(num_threads=8)
    for node in (env, agent, telemetry, orchestrator):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        _wait_until(lambda: clock_publisher.get_subscription_count() >= 2)
        for _ in range(3):
            clock_publisher.publish(_clock(10_000_000_000))
            time.sleep(0.02)
        env.mark_ready()
        agent.mark_ready()
        for _ in range(20):
            clock_publisher.publish(_clock(10_000_000_000))
            if orchestrator.state_history[-1].state == EpisodeState.RUNNING:
                break
            time.sleep(0.02)
        _wait_until(
            lambda: orchestrator.state_history[-1].state == EpisodeState.RUNNING
        )
        _wait_until(lambda: evaluators[0].task_verified)
        _wait_until(lambda: odom_publisher.get_subscription_count() >= 1)
        assert agent.task_state_publisher is not None
        _wait_until(lambda: agent.task_state_publisher.get_subscription_count() >= 1)
        _wait_until(lambda: evaluators[0].transform_ready("odom"))

        odom_publisher.publish(_odometry(10_000_000_000, -1.0, 0.0, 0.0))
        _wait_until(lambda: len(evaluators[0].samples) == 1)

        # Passing through the goal must not finish the Episode on its own.
        clock_publisher.publish(_clock(10_500_000_000))
        odom_publisher.publish(_odometry(10_500_000_000, 2.0, 4.0, 0.0))
        _wait_until(lambda: len(evaluators[0].samples) == 2)
        time.sleep(0.05)
        assert orchestrator.state_history[-1].state == EpisodeState.RUNNING

        # Agent completion plus a ground-truth sample at/after that result is
        # required to commit benchmark success.
        clock_publisher.publish(_clock(11_000_000_000))
        agent.publish_task_state(
            AgentTaskState.SUCCEEDED,
            11_000_000_000,
            sequence=1,
        )
        odom_publisher.publish(_odometry(11_000_000_000, 2.0, 4.0, 0.0))

        _wait_until(
            lambda: orchestrator.state_history[-1].state == EpisodeState.FINISHED
        )
        final = orchestrator.state_history[-1]
        assert final.termination_reason == EpisodeState.SUCCESS
        metrics = evaluators[0].metrics
        assert metrics.success
        assert metrics.elapsed_time_s == pytest.approx(1.0)
        assert metrics.path_length_m == pytest.approx(5.0)
        assert metrics.final_distance_to_goal_m == pytest.approx(0.0)

        own_publishers = dict(
            orchestrator.get_publisher_names_and_types_by_node(
                orchestrator.get_name(),
                orchestrator.get_namespace(),
            )
        )
        assert "/robot/cmd_vel" not in own_publishers
    finally:
        _shutdown(orchestrator, executor, spin_thread, (env, agent, telemetry))


def test_wall_watchdog_reports_frozen_simulation_clock_as_env_error(
    ros_context: None,
) -> None:
    env = _ComponentStub("env")
    agent = _ComponentStub("agent")
    telemetry = rclpy.create_node(f"frozen_clock_telemetry_{uuid4().hex}")
    clock_publisher = telemetry.create_publisher(Clock, "/clock", 1)
    orchestrator = SingleEpisodeOrchestratorNode(
        node_name=f"clock_watchdog_orchestrator_{uuid4().hex}",
        config=_config(),
        parameter_overrides=[
            Parameter("startup_timeout_s", value=1.0),
            Parameter("status_stale_timeout_s", value=0.5),
            Parameter("reset_timeout_s", value=0.2),
            Parameter("safe_stop_timeout_s", value=0.2),
            Parameter("simulation_clock_stale_timeout_s", value=0.1),
        ],
    )
    executor = MultiThreadedExecutor(num_threads=6)
    for node in (env, agent, telemetry, orchestrator):
        executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        deadline = time.monotonic() + 3.0
        while (
            orchestrator.state_history[-1].state != EpisodeState.FINISHED
            and time.monotonic() < deadline
        ):
            clock_publisher.publish(_clock(0))
            time.sleep(0.01)
        assert orchestrator.state_history[-1].state == EpisodeState.FINISHED
        final = orchestrator.state_history[-1]
        assert final.termination_reason == EpisodeState.ENV_ERROR
        assert any(
            "simulation clock stopped" in message.detail
            for message in orchestrator.state_history
        )
    finally:
        _shutdown(orchestrator, executor, spin_thread, (env, agent, telemetry))
