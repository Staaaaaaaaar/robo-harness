"""ROS 2 serial multi-Episode Experiment orchestrator."""

from __future__ import annotations

import math
import os
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
from rh_interfaces.msg import ComponentStatus, EpisodeResult
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rh_interfaces.srv import AbortEpisode, ResetAgent, ResetEnv, StartEpisode
from rosgraph_msgs.msg import Clock as ClockMessage

from rh_core import (
    EpisodeState,
    ExecutionMode,
    ExperimentConfig,
    ExperimentState,
    TerminationReason,
    load_experiment_config,
)
from rh_experiment.controller import ControlDecision, ExperimentController
from rh_experiment.evaluation import (
    EpisodeEvaluationResult,
    EpisodeEvaluator,
    EpisodeEvaluatorFactory,
)
from rh_experiment.recorder import (
    EpisodeMetrics,
    ResultRecorder,
    RuntimeMetadata,
)
from rh_experiment.task import EpisodeTaskPublisher, EpisodeTaskPublisherFactory
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


class ExperimentOrchestratorNode(Node):
    """Serialize an ordered Experiment lifecycle on one control thread."""

    def __init__(
        self,
        *,
        node_name: str = "rh_experiment_orchestrator",
        parameter_overrides: list[Parameter] | None = None,
        config: ExperimentConfig | None = None,
        task_publisher_factory: EpisodeTaskPublisherFactory | None = None,
        evaluator_factory: EpisodeEvaluatorFactory | None = None,
        recorder: ResultRecorder | None = None,
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
        self.declare_parameter("simulation_clock_stale_timeout_s", 5.0)
        self.declare_parameter("results_root", "")
        self.declare_parameter("git_sha", "")
        self.declare_parameter("isaac_version", "")

        runtime_config = config or self._load_config_parameter()
        self._config = runtime_config
        self._episode_specs = runtime_config.experiment.episodes
        episode = self._episode_specs[0]
        configured_id = str(self.get_parameter("experiment_id").value).strip()
        experiment_id = configured_id or runtime_config.experiment.name
        self._episode_spec = episode
        self._controller = ExperimentController(
            experiment_id=experiment_id,
            episode_ids=tuple(item.episode_id for item in self._episode_specs),
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
        self._simulation_clock_stale_timeout_s = self._positive_parameter(
            "simulation_clock_stale_timeout_s"
        )
        self._env_component_id = self._non_empty_parameter("env_component_id")
        self._agent_component_id = self._non_empty_parameter("agent_component_id")

        self._state_publisher = self.create_publisher(
            EpisodeStateMessage,
            "/roboharness/episode/state",
            latched_control_qos(),
        )
        self._result_publisher = self.create_publisher(
            EpisodeResult,
            "/roboharness/episode/result",
            10,
        )
        self._task_publisher_factory = task_publisher_factory
        self._evaluator_factory = evaluator_factory
        self._task_publisher: EpisodeTaskPublisher | None = None
        self._evaluator: EpisodeEvaluator | None = None
        self._recorder = recorder or self._recorder_from_parameters(
            runtime_config,
            experiment_id,
        )
        self._clock_lock = threading.Lock()
        self._last_clock_nanoseconds: int | None = None
        self._last_clock_wall_time: float | None = None
        self._running_wall_time: float | None = None
        self._clock_subscription = self.create_subscription(
            ClockMessage,
            "/clock",
            self._on_clock,
            1,
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
        self._preparation_deadline = time.monotonic() + self._startup_timeout_s
        self._startup_complete = False
        self._finalization_started = False
        self._stop_after_episode = False
        self._experiment_finalized = False
        if self._recorder is not None:
            self._recorder.start()
            self._recorder.begin_episode(self._episode_spec)
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
            episode_id=self.episode_id,
            termination_reason=reason,
            detail=detail,
        )
        return self._submit_event(event)

    def _submit_episode_termination(
        self,
        episode_id: str,
        reason: TerminationReason,
        *,
        detail: str,
    ) -> ControlDecision:
        if not isinstance(reason, TerminationReason):
            return ControlDecision(False, "reason must be a TerminationReason")
        return self._submit_event(
            _ControlEvent(
                kind="terminate",
                episode_id=episode_id,
                termination_reason=reason,
                detail=detail,
            )
        )

    def _load_config_parameter(self) -> ExperimentConfig:
        config_path = str(self.get_parameter("config_path").value).strip()
        if not config_path:
            raise ValueError("config_path is required")
        return load_experiment_config(config_path)

    def _recorder_from_parameters(
        self,
        config: ExperimentConfig,
        experiment_id: str,
    ) -> ResultRecorder | None:
        results_root = str(self.get_parameter("results_root").value).strip()
        if not results_root:
            return None
        git_sha = str(self.get_parameter("git_sha").value).strip() or None
        isaac_version = (
            str(self.get_parameter("isaac_version").value).strip() or None
        )
        return ResultRecorder(
            results_root,
            experiment_id,
            config,
            runtime=RuntimeMetadata(
                git_sha=git_sha,
                ros_distro=os.environ.get("ROS_DISTRO") or None,
                isaac_version=isaac_version,
            ),
        )

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
                if self._episode_state() is EpisodeState.PREPARING:
                    self._preparation_tick()
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

    def _preparation_tick(self) -> None:
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
            if time.monotonic() >= self._preparation_deadline:
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
            if not self._startup_complete:
                self._controller.mark_components_ready()
                self._startup_complete = True
        if not self._create_episode_resources():
            return
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
        request.request_id = f"{self._run_id}:{self.episode_id}:env-reset"
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

    def _create_episode_resources(self) -> bool:
        if self._task_publisher is not None or self._evaluator is not None:
            return True
        try:
            if self._task_publisher_factory is not None:
                self._task_publisher = self._task_publisher_factory(
                    self,
                    self.experiment_id,
                    self._episode_spec,
                )
            if self._evaluator_factory is not None:
                active_episode_id = self.episode_id

                def submit_bound(
                    reason: TerminationReason,
                    *,
                    detail: str,
                ) -> ControlDecision:
                    return self._submit_episode_termination(
                        active_episode_id,
                        reason,
                        detail=detail,
                    )

                self._evaluator = self._evaluator_factory(
                    self,
                    self.experiment_id,
                    self._episode_spec,
                    submit_bound,
                )
        except Exception as error:
            self._close_episode_resources()
            self._commit_episode_termination(
                TerminationReason.INVALID_TASK,
                f"Episode implementation rejected the task: {error}",
                stop_experiment=False,
            )
            return False
        return True

    def _reset_agent(self) -> bool:
        request = ResetAgent.Request()
        request.request_id = f"{self._run_id}:{self.episode_id}:agent-reset"
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
        if self._episode_state() is EpisodeState.RUNNING:
            with self._clock_lock:
                references = tuple(
                    value
                    for value in (
                        self._last_clock_wall_time,
                        self._running_wall_time,
                    )
                    if value is not None
                )
                reference = max(references) if references else None
            if (
                reference is not None
                and time.monotonic() - reference
                >= self._simulation_clock_stale_timeout_s
            ):
                self._commit_infrastructure_failure(
                    TerminationReason.ENV_ERROR,
                    "simulation clock stopped advancing",
                )
                return

    def _on_clock(self, message: ClockMessage) -> None:
        simulation_nanoseconds = (
            int(message.clock.sec) * 1_000_000_000 + int(message.clock.nanosec)
        )
        running = self._episode_state() is EpisodeState.RUNNING
        with self._clock_lock:
            advances = (
                self._last_clock_nanoseconds is None
                or simulation_nanoseconds > self._last_clock_nanoseconds
                or (
                    not running
                    and simulation_nanoseconds != self._last_clock_nanoseconds
                )
            )
            if advances:
                self._last_clock_nanoseconds = simulation_nanoseconds
                self._last_clock_wall_time = time.monotonic()

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
            if event.episode_id != self.episode_id:
                return ControlDecision(
                    False,
                    "termination candidate does not match the active Episode",
                )
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
            with self._clock_lock:
                self._running_wall_time = time.monotonic()
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
        self._commit_episode_termination(reason, detail, stop_experiment=True)

    def _commit_episode_termination(
        self,
        reason: TerminationReason,
        detail: str,
        *,
        stop_experiment: bool,
    ) -> None:
        self._stop_after_episode = self._stop_after_episode or stop_experiment
        with self._state_lock:
            if stop_experiment:
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
        reason = self._termination_reason()
        evaluation = self._finalize_evaluation(reason)
        result_uri = self._persist_episode(evaluation, reason, detail)

        last_episode = not self._controller.has_next_episode
        if self._recorder is not None and (self._stop_after_episode or last_episode):
            self._finish_recorder(complete=last_episode and not self._stop_after_episode)
        with self._state_lock:
            self._controller.finish_termination(
                stop_experiment=self._stop_after_episode,
            )
        self._publish_state(detail, record_event=False)
        self._publish_result(evaluation.metrics, result_uri)
        self._close_episode_resources()

        if not self._stop_after_episode and self._controller.has_next_episode:
            self._advance_episode()
        else:
            self._experiment_finalized = True

    def _finalize_evaluation(
        self,
        reason: TerminationReason,
    ) -> EpisodeEvaluationResult:
        simulation_time_s = self._simulation_time_s()
        if self._evaluator is not None:
            try:
                result = self._evaluator.finalize(reason, simulation_time_s)
                if result.metrics.termination_reason is not reason:
                    raise ValueError(
                        "evaluator metrics disagree with committed termination reason"
                    )
                return result
            except Exception as error:
                self.get_logger().error(f"evaluator finalization failed: {error}")
                self._stop_after_episode = True
                with self._state_lock:
                    self._controller.fail_experiment()
        return EpisodeEvaluationResult(
            metrics=EpisodeMetrics(
                success=reason is TerminationReason.SUCCESS,
                elapsed_time_s=0.0,
                path_length_m=0.0,
                final_distance_to_goal_m=None,
                timeout=reason is TerminationReason.TIMEOUT,
                termination_reason=reason,
                sample_count=0,
            ),
            trajectory=(),
        )

    def _persist_episode(
        self,
        evaluation: EpisodeEvaluationResult,
        reason: TerminationReason,
        detail: str,
    ) -> str:
        if self._recorder is None:
            return ""
        try:
            self._recorder.record_event(
                self.episode_id,
                "episode_finished",
                simulation_time_s=self._simulation_time_s(),
                detail=detail,
                payload={"termination_reason": reason.name},
            )
            return self._recorder.complete_episode(
                self.episode_id,
                evaluation.metrics,
                evaluation.trajectory,
            )
        except Exception as error:
            self.get_logger().error(f"result persistence failed: {error}")
            self._stop_after_episode = True
            with self._state_lock:
                self._controller.fail_experiment()
            return ""

    def _finish_recorder(self, *, complete: bool) -> None:
        assert self._recorder is not None
        try:
            self._recorder.finish(complete=complete)
        except Exception as error:
            self.get_logger().error(f"Experiment result commit failed: {error}")
            self._stop_after_episode = True
            with self._state_lock:
                self._controller.fail_experiment()
            if complete:
                try:
                    self._recorder.finish(complete=False)
                except Exception as fallback_error:
                    self.get_logger().error(
                        f"incomplete result marker also failed: {fallback_error}"
                    )

    def _publish_result(self, metrics: EpisodeMetrics, result_uri: str) -> None:
        message = EpisodeResult()
        message.experiment_id = self.experiment_id
        message.episode_id = self.episode_id
        message.termination_reason = int(metrics.termination_reason)
        message.success = metrics.success
        message.elapsed_time_s = metrics.elapsed_time_s
        message.path_length_m = metrics.path_length_m
        message.final_distance_to_goal_m = (
            metrics.final_distance_to_goal_m
            if metrics.final_distance_to_goal_m is not None
            else math.nan
        )
        message.result_uri = result_uri
        self._result_publisher.publish(message)

    def _advance_episode(self) -> None:
        with self._state_lock:
            self._controller.advance_episode()
            self._episode_spec = self._episode_specs[self._controller.episode_index]
        self._task_publisher = None
        self._evaluator = None
        self._finalization_started = False
        self._stop_after_episode = False
        self._preparation_deadline = time.monotonic() + self._startup_timeout_s
        with self._clock_lock:
            self._running_wall_time = None
        if self._recorder is not None:
            self._recorder.begin_episode(self._episode_spec)
        self._publish_state("waiting for Env and Agent readiness")

    def _close_episode_resources(self) -> None:
        for resource in (self._evaluator, self._task_publisher):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as error:
                self.get_logger().warning(
                    f"failed to close Episode resource: {error}"
                )
        self._evaluator = None
        self._task_publisher = None

    def _simulation_time_s(self) -> float:
        with self._clock_lock:
            nanoseconds = self._last_clock_nanoseconds
        return 0.0 if nanoseconds is None else nanoseconds / 1_000_000_000.0

    def _termination_reason(self) -> TerminationReason:
        with self._state_lock:
            return self._controller.episode.termination_reason

    def _safe_stop_handshake(self) -> bool:
        deadline = time.monotonic() + self._safe_stop_timeout_s
        while not self._stop_requested.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            self._publish_state(
                "waiting for safe-stop state delivery",
                record_event=False,
            )
            if self._state_publisher.get_subscription_count() >= 2:
                timeout = Duration(seconds=min(0.05, remaining))
                if self._state_publisher.wait_for_all_acked(timeout):
                    return True
            self._stop_requested.wait(min(0.01, remaining))
        return False

    def _publish_state(self, detail: str, *, record_event: bool = True) -> None:
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
        if self._recorder is not None and record_event:
            self._recorder.record_event(
                self.episode_id,
                "episode_state",
                simulation_time_s=self._simulation_time_s(),
                detail=detail,
                payload={
                    "state": int(message.state),
                    "termination_reason": int(message.termination_reason),
                    "sequence": int(message.sequence),
                },
            )

    def _episode_state(self) -> EpisodeState:
        with self._state_lock:
            return self._controller.episode.state

    def stop(self) -> None:
        """Stop the control thread before executor and ROS entity teardown."""

        self._stop_requested.set()
        if hasattr(self, "_worker") and self._worker.is_alive():
            self._worker.join(timeout=self._control_request_timeout_s)
        if hasattr(self, "_evaluator"):
            self._close_episode_resources()
        if (
            hasattr(self, "_recorder")
            and self._recorder is not None
            and not self._experiment_finalized
        ):
            try:
                self._recorder.finish(complete=False)
            except Exception as error:
                self.get_logger().warning(
                    f"failed to finalize interrupted result: {error}"
                )
            self._experiment_finalized = True

    def destroy_node(self) -> bool:
        if hasattr(self, "_stop_requested"):
            self.stop()
        return super().destroy_node()


# Preserve the PR7 import while widening its implementation to multi-Episode.
SingleEpisodeOrchestratorNode = ExperimentOrchestratorNode


def main(
    args: list[str] | None = None,
    *,
    task_publisher_factory: EpisodeTaskPublisherFactory | None = None,
    evaluator_factory: EpisodeEvaluatorFactory | None = None,
) -> None:
    rclpy.init(args=args)
    node = ExperimentOrchestratorNode(
        task_publisher_factory=task_publisher_factory,
        evaluator_factory=evaluator_factory,
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
