"""ROS 2 single-Episode Experiment orchestrator."""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4

import rclpy
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import ComponentStatus
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rh_interfaces.srv import AbortEpisode, ResetAgent, ResetEnv, StartEpisode

from rh_core import (
    EpisodeState,
    ExecutionMode,
    ExperimentConfig,
    ExperimentState,
    TerminationReason,
    load_experiment_config,
)
from rh_experiment.controller import ControlDecision, SingleEpisodeController
from rh_experiment.task import EpisodeTaskPublisherFactory
from rh_ros import (
    ServiceCallError,
    ServiceCallTimeoutError,
    ServiceDiscoveryTimeoutError,
    StatusMonitor,
    call_service_with_deadline,
    episode_state_to_message,
    latched_control_qos,
    pose_to_message,
)


@dataclass(slots=True)
class _ControlEvent:
    kind: str
    experiment_id: str = ""
    episode_id: str = ""
    abort_reason: str = ""
    termination_reason: TerminationReason = TerminationReason.NONE
    detail: str = ""
    completed: threading.Event = field(default_factory=threading.Event)
    guard: threading.Lock = field(default_factory=threading.Lock)
    decision: ControlDecision | None = None
    claimed: bool = False
    cancelled: bool = False


class SingleEpisodeOrchestratorNode(Node):
    """Serialize one Episode lifecycle on a dedicated control thread."""

    def __init__(
        self,
        *,
        node_name: str = "rh_experiment_orchestrator",
        parameter_overrides: list[Parameter] | None = None,
        config: ExperimentConfig | None = None,
        task_publisher_factory: EpisodeTaskPublisherFactory | None = None,
    ) -> None:
        overrides = list(parameter_overrides or [])
        if not any(parameter.name == "use_sim_time" for parameter in overrides):
            overrides.append(Parameter("use_sim_time", value=True))
        super().__init__(
            node_name,
            parameter_overrides=overrides,
            automatically_declare_parameters_from_overrides=False,
        )
        self.declare_parameter("config_path", "")
        self.declare_parameter("experiment_id", "")
        self.declare_parameter("env_component_id", "env")
        self.declare_parameter("agent_component_id", "agent")
        self.declare_parameter("startup_timeout_s", 300.0)
        self.declare_parameter("status_stale_timeout_s", 5.0)
        self.declare_parameter("reset_timeout_s", 30.0)
        self.declare_parameter("safe_stop_timeout_s", 2.0)
        self.declare_parameter("control_request_timeout_s", 2.0)

        runtime_config = config or self._load_config_parameter()
        if len(runtime_config.experiment.episodes) != 1:
            raise ValueError("PR7 orchestrator requires exactly one Episode")
        episode = runtime_config.experiment.episodes[0]
        configured_id = str(self.get_parameter("experiment_id").value).strip()
        experiment_id = configured_id or runtime_config.experiment.name
        self._episode_spec = episode
        self._controller = SingleEpisodeController(
            experiment_id=experiment_id,
            episode_id=episode.episode_id,
            execution_mode=runtime_config.experiment.execution_mode,
        )
        self._state_lock = threading.Lock()
        self._state_history: list[EpisodeStateMessage] = []

        self._startup_timeout_s = self._positive_parameter("startup_timeout_s")
        stale_timeout = self._positive_parameter("status_stale_timeout_s")
        self._reset_timeout_s = self._positive_parameter("reset_timeout_s")
        self._safe_stop_timeout_s = self._positive_parameter("safe_stop_timeout_s")
        self._control_request_timeout_s = self._positive_parameter(
            "control_request_timeout_s"
        )
        self._env_component_id = self._non_empty_parameter("env_component_id")
        self._agent_component_id = self._non_empty_parameter("agent_component_id")

        self._state_publisher = self.create_publisher(
            EpisodeStateMessage,
            "/roboharness/episode/state",
            latched_control_qos(),
        )
        self._task_publisher = (
            task_publisher_factory(self, experiment_id, episode)
            if task_publisher_factory is not None
            else None
        )
        self._env_status = StatusMonitor(
            self,
            "/roboharness/env/status",
            stale_timeout_s=stale_timeout,
        )
        self._agent_status = StatusMonitor(
            self,
            "/roboharness/agent/status",
            stale_timeout_s=stale_timeout,
        )
        self._env_reset_client = self.create_client(
            ResetEnv,
            "/roboharness/env/reset_episode",
        )
        self._agent_reset_client = self.create_client(
            ResetAgent,
            "/roboharness/agent/reset_episode",
        )
        self._start_service = self.create_service(
            StartEpisode,
            "/roboharness/episode/start",
            self._on_start,
        )
        self._abort_service = self.create_service(
            AbortEpisode,
            "/roboharness/episode/abort",
            self._on_abort,
        )

        self._events: queue.Queue[_ControlEvent] = queue.Queue()
        self._stop_requested = threading.Event()
        self._run_id = uuid4().hex
        self._startup_deadline = time.monotonic() + self._startup_timeout_s
        self._startup_complete = False
        self._finalization_started = False
        self._publish_state("waiting for Env and Agent readiness")
        self._worker = threading.Thread(
            target=self._control_loop,
            name=f"{node_name}-control",
            daemon=True,
        )
        self._worker.start()

    @property
    def experiment_id(self) -> str:
        return self._controller.experiment_id

    @property
    def episode_id(self) -> str:
        return self._controller.episode.episode_id

    @property
    def state_history(self) -> tuple[EpisodeStateMessage, ...]:
        with self._state_lock:
            return tuple(self._state_history)

    @property
    def experiment_state(self) -> ExperimentState:
        with self._state_lock:
            return self._controller.experiment.state

    def submit_termination(
        self,
        reason: TerminationReason,
        *,
        detail: str,
    ) -> ControlDecision:
        """Future in-process Evaluators use this same serialized commit path."""

        if not isinstance(reason, TerminationReason):
            return ControlDecision(False, "reason must be a TerminationReason")
        event = _ControlEvent(
            kind="terminate",
            termination_reason=reason,
            detail=detail,
        )
        return self._submit_event(event)

    def _load_config_parameter(self) -> ExperimentConfig:
        config_path = str(self.get_parameter("config_path").value).strip()
        if not config_path:
            raise ValueError("config_path is required")
        return load_experiment_config(config_path)

    def _positive_parameter(self, name: str) -> float:
        value = self.get_parameter(name).value
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0.0
        ):
            raise ValueError(f"{name} must be finite and positive")
        return float(value)

    def _non_empty_parameter(self, name: str) -> str:
        value = self.get_parameter(name).value
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be empty")
        return value

    def _on_start(
        self, request: StartEpisode.Request, response: StartEpisode.Response
    ) -> StartEpisode.Response:
        decision = self._submit_event(
            _ControlEvent(
                kind="start",
                experiment_id=request.experiment_id,
                episode_id=request.episode_id,
            )
        )
        response.accepted = decision.accepted
        response.detail = decision.detail
        return response

    def _on_abort(
        self, request: AbortEpisode.Request, response: AbortEpisode.Response
    ) -> AbortEpisode.Response:
        decision = self._submit_event(
            _ControlEvent(
                kind="abort",
                experiment_id=request.experiment_id,
                episode_id=request.episode_id,
                abort_reason=request.reason,
            )
        )
        response.accepted = decision.accepted
        response.detail = decision.detail
        return response

    def _submit_event(self, event: _ControlEvent) -> ControlDecision:
        if self._stop_requested.is_set():
            return ControlDecision(False, "orchestrator is shutting down")
        self._events.put(event)
        if not event.completed.wait(self._control_request_timeout_s):
            with event.guard:
                if not event.claimed:
                    event.cancelled = True
                    return ControlDecision(False, "control request timed out")
            # A claimed handler contains no blocking ROS operation. Once a
            # transition may be committed, return its real decision instead of
            # contradicting the authoritative state topic.
            event.completed.wait()
        assert event.decision is not None
        return event.decision

    def _process_event(self, event: _ControlEvent) -> None:
        with event.guard:
            if event.cancelled:
                event.decision = ControlDecision(False, "control request expired")
                event.completed.set()
                return
            event.claimed = True
        try:
            if event.kind == "stop":
                event.decision = ControlDecision(True, "orchestrator stopped")
            else:
                event.decision = self._handle_event(event)
        except BaseException:
            event.decision = ControlDecision(False, "control request failed")
            raise
        finally:
            event.completed.set()

    def _control_loop(self) -> None:
        while not self._stop_requested.is_set():
            try:
                if not self._startup_complete and self._episode_state() is EpisodeState.PREPARING:
                    self._startup_tick()
                self._runtime_health_tick()
                self._finalization_tick()
                try:
                    event = self._events.get(timeout=0.02)
                except queue.Empty:
                    continue
                self._process_event(event)
            except BaseException as error:  # keep a visible terminal snapshot
                self.get_logger().error(f"orchestrator control failure: {error}")
                self._commit_infrastructure_failure(
                    TerminationReason.FAILURE,
                    f"orchestrator control failure: {error}",
                )

    def _startup_tick(self) -> None:
        env_message = self._env_status.tracker.latest(self._env_component_id)
        agent_message = self._agent_status.tracker.latest(self._agent_component_id)
        if env_message is not None and env_message.state == ComponentStatus.ERROR:
            self._commit_infrastructure_failure(
                TerminationReason.ENV_ERROR,
                f"Env ERROR: {env_message.detail}",
            )
            return
        if agent_message is not None and agent_message.state == ComponentStatus.ERROR:
            self._commit_infrastructure_failure(
                TerminationReason.AGENT_ERROR,
                f"Agent ERROR: {agent_message.detail}",
            )
            return
        env_ready = self._env_status.tracker.is_ready(self._env_component_id)
        agent_ready = self._agent_status.tracker.is_ready(self._agent_component_id)
        if not (env_ready and agent_ready):
            if time.monotonic() >= self._startup_deadline:
                reason = (
                    TerminationReason.ENV_ERROR
                    if not env_ready
                    else TerminationReason.AGENT_ERROR
                )
                missing = "Env" if not env_ready else "Agent"
                self._commit_infrastructure_failure(
                    reason,
                    f"{missing} did not become READY before startup deadline",
                )
            return

        with self._state_lock:
            self._controller.mark_components_ready()
        self._startup_complete = True
        if not self._reset_environment():
            return
        if not self._reset_agent():
            return
        if not self._publish_episode_task():
            return
        with self._state_lock:
            self._controller.mark_prepared()
        self._publish_state("Episode preparation complete")
        if self._controller.execution_mode is ExecutionMode.AUTOMATIC:
            self._start_active_episode()

    def _reset_environment(self) -> bool:
        request = ResetEnv.Request()
        request.request_id = f"{self._run_id}:env-reset"
        request.experiment_id = self.experiment_id
        request.episode_id = self.episode_id
        request.initial_pose = pose_to_message(self._episode_spec.initial_pose)
        request.seed = self._episode_spec.seed
        try:
            response = call_service_with_deadline(
                self._env_reset_client,
                request,
                discovery_timeout_s=self._reset_timeout_s,
                call_timeout_s=self._reset_timeout_s,
            )
        except (
            ServiceCallError,
            ServiceCallTimeoutError,
            ServiceDiscoveryTimeoutError,
        ) as error:
            self._commit_infrastructure_failure(
                TerminationReason.ENV_ERROR,
                f"Env reset failed: {error}",
            )
            return False
        if not response.success:
            self._commit_infrastructure_failure(
                TerminationReason.ENV_ERROR,
                f"Env reset rejected ({response.error_code}): {response.detail}",
            )
            return False
        return True

    def _publish_episode_task(self) -> bool:
        if self._task_publisher is None:
            return True
        try:
            self._task_publisher.publish()
        except Exception as error:
            self._commit_infrastructure_failure(
                TerminationReason.FAILURE,
                f"task publication failed: {error}",
            )
            return False
        return True

    def _reset_agent(self) -> bool:
        request = ResetAgent.Request()
        request.request_id = f"{self._run_id}:agent-reset"
        request.experiment_id = self.experiment_id
        request.episode_id = self.episode_id
        try:
            response = call_service_with_deadline(
                self._agent_reset_client,
                request,
                discovery_timeout_s=self._reset_timeout_s,
                call_timeout_s=self._reset_timeout_s,
            )
        except (
            ServiceCallError,
            ServiceCallTimeoutError,
            ServiceDiscoveryTimeoutError,
        ) as error:
            self._commit_infrastructure_failure(
                TerminationReason.AGENT_ERROR,
                f"Agent reset failed: {error}",
            )
            return False
        if not response.success:
            self._commit_infrastructure_failure(
                TerminationReason.AGENT_ERROR,
                f"Agent reset rejected ({response.error_code}): {response.detail}",
            )
            return False
        return True

    def _runtime_health_tick(self) -> None:
        if self._episode_state() not in {EpisodeState.READY, EpisodeState.RUNNING}:
            return
        for tracker, component_id, reason, label in (
            (
                self._env_status.tracker,
                self._env_component_id,
                TerminationReason.ENV_ERROR,
                "Env",
            ),
            (
                self._agent_status.tracker,
                self._agent_component_id,
                TerminationReason.AGENT_ERROR,
                "Agent",
            ),
        ):
            message = tracker.latest(component_id)
            if message is not None and message.state == ComponentStatus.ERROR:
                self._commit_infrastructure_failure(
                    reason,
                    f"{label} ERROR: {message.detail}",
                )
                return
            if tracker.is_stale(component_id):
                self._commit_infrastructure_failure(
                    reason,
                    f"{label} status heartbeat became stale",
                )
                return

    def _handle_event(self, event: _ControlEvent) -> ControlDecision:
        if event.kind == "start":
            return self._request_start(event.experiment_id, event.episode_id)
        if event.kind == "abort":
            with self._state_lock:
                decision = self._controller.request_abort(
                    event.experiment_id,
                    event.episode_id,
                    event.abort_reason,
                )
            if decision.accepted:
                self._publish_state(decision.detail)
            return decision
        if event.kind == "terminate":
            with self._state_lock:
                decision = self._controller.request_termination(
                    event.termination_reason,
                    detail=event.detail,
                )
            if decision.accepted:
                self._publish_state(event.detail)
            return decision
        return ControlDecision(False, f"unknown control event {event.kind!r}")

    def _request_start(self, experiment_id: str, episode_id: str) -> ControlDecision:
        with self._state_lock:
            decision = self._controller.request_start(experiment_id, episode_id)
        if decision.accepted:
            self._publish_state(decision.detail)
        return decision

    def _start_active_episode(self) -> None:
        decision = self._request_start(self.experiment_id, self.episode_id)
        if not decision.accepted:
            self._commit_infrastructure_failure(
                TerminationReason.FAILURE,
                f"automatic start failed: {decision.detail}",
            )

    def _commit_infrastructure_failure(
        self,
        reason: TerminationReason,
        detail: str,
    ) -> None:
        with self._state_lock:
            self._controller.fail_experiment()
            decision = self._controller.request_termination(reason, detail=detail)
        if decision.accepted:
            self._publish_state(detail)

    def _finalization_tick(self) -> None:
        if self._episode_state() is not EpisodeState.TERMINATING:
            return
        if self._finalization_started:
            return
        self._finalization_started = True
        acknowledged = self._safe_stop_handshake()
        detail = (
            "safe-stop state delivery acknowledged"
            if acknowledged
            else "safe-stop state delivery deadline expired"
        )
        with self._state_lock:
            self._controller.finish_termination()
        self._publish_state(detail)

    def _safe_stop_handshake(self) -> bool:
        deadline = time.monotonic() + self._safe_stop_timeout_s
        while not self._stop_requested.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            self._publish_state("waiting for safe-stop state delivery")
            if self._state_publisher.get_subscription_count() >= 2:
                timeout = Duration(seconds=min(0.05, remaining))
                if self._state_publisher.wait_for_all_acked(timeout):
                    return True
            self._stop_requested.wait(min(0.01, remaining))
        return False

    def _publish_state(self, detail: str) -> None:
        with self._state_lock:
            lifecycle = self._controller.episode
            message = episode_state_to_message(
                self.experiment_id,
                lifecycle,
                stamp=self.get_clock().now().to_msg(),
                detail=detail,
            )
            self._state_history.append(message)
        self._state_publisher.publish(message)

    def _episode_state(self) -> EpisodeState:
        with self._state_lock:
            return self._controller.episode.state

    def stop(self) -> None:
        """Stop the control thread before executor and ROS entity teardown."""

        self._stop_requested.set()
        if hasattr(self, "_worker") and self._worker.is_alive():
            self._worker.join(timeout=self._control_request_timeout_s)

    def destroy_node(self) -> bool:
        if hasattr(self, "_stop_requested"):
            self.stop()
        return super().destroy_node()


def main(
    args: list[str] | None = None,
    *,
    task_publisher_factory: EpisodeTaskPublisherFactory | None = None,
) -> None:
    rclpy.init(args=args)
    node = SingleEpisodeOrchestratorNode(
        task_publisher_factory=task_publisher_factory,
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.stop()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
