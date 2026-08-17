"""Versioned Result Recorder with explicit Episode and Experiment commits."""

from __future__ import annotations

import csv
import io
import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rh_core import (
    EpisodeSpec,
    ExperimentConfig,
    Point3D,
    PointNavTaskSpec,
    Pose3D,
    TerminationReason,
)
from rh_experiment.recorder.io import (
    atomic_write_json,
    atomic_write_text,
    atomic_write_yaml,
)
from rh_experiment.recorder.models import (
    EpisodeMetrics,
    ResultEvent,
    RuntimeMetadata,
    TrajectoryPoint,
)
from rh_experiment.recorder.paths import safe_path_component
from rh_experiment.recorder.schema import RESULT_SCHEMA_VERSION

_TRAJECTORY_FIELDS = ("simulation_time_s", "frame_id", "x", "y", "z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware datetime values")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _point_document(point: Point3D) -> dict[str, object]:
    return {
        "frame_id": point.frame_id,
        "x": point.x,
        "y": point.y,
        "z": point.z,
    }


def _pose_document(pose: Pose3D) -> dict[str, object]:
    return {
        "frame_id": pose.frame_id,
        "x": pose.x,
        "y": pose.y,
        "z": pose.z,
        "roll": pose.roll,
        "pitch": pose.pitch,
        "yaw": pose.yaw,
    }


def _task_document(task: PointNavTaskSpec) -> dict[str, object]:
    return {
        "type": "pointnav",
        "goal": _point_document(task.goal),
        "success_radius_m": task.success_radius_m,
        "timeout_s": task.timeout_s,
    }


def _episode_document(episode: EpisodeSpec) -> dict[str, object]:
    return {
        "episode_id": episode.episode_id,
        "scenario": episode.scenario,
        "initial_pose": _pose_document(episode.initial_pose),
        "task": _task_document(episode.task),
        "seed": episode.seed,
    }


def _config_document(config: ExperimentConfig) -> dict[str, object]:
    return {
        "schema_version": config.schema_version,
        "experiment": {
            "name": config.experiment.name,
            "execution_mode": config.experiment.execution_mode.value,
            "episodes": [
                _episode_document(episode) for episode in config.experiment.episodes
            ],
        },
    }


@dataclass(slots=True)
class _EpisodeBuffer:
    spec: EpisodeSpec
    directory: Path
    events: list[ResultEvent] = field(default_factory=list)
    complete: bool = False
    termination_reason: TerminationReason = TerminationReason.NONE


class ResultRecorder:
    """Write one Experiment result tree without owning its lifecycle."""

    def __init__(
        self,
        results_root: str | Path,
        experiment_id: str,
        config: ExperimentConfig,
        *,
        runtime: RuntimeMetadata | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(config, ExperimentConfig):
            raise TypeError("config must be an ExperimentConfig")
        if not callable(now):
            raise TypeError("now must be callable")
        self.results_root = Path(results_root)
        self.experiment_id = experiment_id
        self.experiment_directory = (
            self.results_root / safe_path_component(experiment_id)
        )
        self._config = config
        self._runtime = runtime or RuntimeMetadata()
        self._now = now
        self._lock = threading.RLock()
        self._episodes: dict[str, _EpisodeBuffer] = {}
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._started = False
        self._finished = False

    def start(self) -> Path:
        """Create a new result tree with durable incomplete commit markers."""

        with self._lock:
            if self._started:
                raise RuntimeError("result recording has already started")
            self.results_root.mkdir(parents=True, exist_ok=True)
            self.experiment_directory.mkdir(parents=False, exist_ok=False)
            (self.experiment_directory / "episodes").mkdir()
            self._started_at = _timestamp(self._now())
            self._started = True
            atomic_write_yaml(
                self.experiment_directory / "config.yaml",
                _config_document(self._config),
            )
            self._write_summary(complete=False)
            self._write_metadata(complete=False)
            return self.experiment_directory

    def begin_episode(self, episode: EpisodeSpec) -> Path:
        """Persist an Episode spec and parseable incomplete artifacts."""

        if not isinstance(episode, EpisodeSpec):
            raise TypeError("episode must be an EpisodeSpec")
        with self._lock:
            self._require_active()
            if episode.episode_id in self._episodes:
                raise ValueError(f"duplicate Episode ID {episode.episode_id!r}")
            if episode not in self._config.experiment.episodes:
                raise ValueError("episode is not present in the recorded config")
            directory = (
                self.experiment_directory
                / "episodes"
                / safe_path_component(episode.episode_id)
            )
            directory.mkdir(parents=False, exist_ok=False)
            buffer = _EpisodeBuffer(spec=episode, directory=directory)
            self._episodes[episode.episode_id] = buffer
            atomic_write_yaml(
                directory / "episode.yaml",
                {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "experiment_id": self.experiment_id,
                    "episode": _episode_document(episode),
                },
            )
            atomic_write_text(directory / "events.jsonl", "")
            atomic_write_text(
                directory / "trajectory.csv",
                ",".join(_TRAJECTORY_FIELDS) + "\n",
            )
            atomic_write_json(
                directory / "metrics.json",
                self._metrics_document(episode.episode_id, None),
            )
            self._write_summary(complete=False)
            return directory

    def record_event(
        self,
        episode_id: str,
        event: str,
        *,
        simulation_time_s: float | None = None,
        detail: str = "",
        payload: dict[str, object] | None = None,
    ) -> ResultEvent:
        """Append one low-rate event using an atomic full-file replacement."""

        with self._lock:
            buffer = self._active_episode(episode_id)
            result_event = ResultEvent(
                sequence=len(buffer.events),
                event=event,
                simulation_time_s=simulation_time_s,
                detail=detail,
                payload=dict(payload or {}),
            )
            buffer.events.append(result_event)
            try:
                self._write_events(buffer)
            except Exception:
                buffer.events.pop()
                raise
            return result_event

    def complete_episode(
        self,
        episode_id: str,
        metrics: EpisodeMetrics,
        trajectory: Sequence[TrajectoryPoint],
    ) -> str:
        """Commit final trajectory first and metrics last for one Episode."""

        if not isinstance(metrics, EpisodeMetrics):
            raise TypeError("metrics must be EpisodeMetrics")
        with self._lock:
            buffer = self._active_episode(episode_id)
            samples = tuple(trajectory)
            self._validate_trajectory(samples, metrics.sample_count)
            atomic_write_text(
                buffer.directory / "trajectory.csv",
                self._trajectory_csv(samples),
            )
            self._write_events(buffer)
            atomic_write_json(
                buffer.directory / "metrics.json",
                self._metrics_document(episode_id, metrics),
            )
            buffer.complete = True
            buffer.termination_reason = metrics.termination_reason
            self._write_summary(complete=False)
            return (buffer.directory / "metrics.json").resolve().as_uri()

    def finish(self, *, complete: bool = True) -> None:
        """Commit the Experiment manifest last, or preserve an incomplete run."""

        if not isinstance(complete, bool):
            raise TypeError("complete must be a bool")
        with self._lock:
            self._require_active()
            if complete:
                configured_ids = {
                    episode.episode_id for episode in self._config.experiment.episodes
                }
                if set(self._episodes) != configured_ids or any(
                    not episode.complete for episode in self._episodes.values()
                ):
                    raise RuntimeError(
                        "cannot complete an Experiment with missing or open Episodes"
                    )
            self._finished_at = _timestamp(self._now())
            self._write_summary(complete=complete)
            self._write_metadata(complete=complete)
            self._finished = True

    def _require_active(self) -> None:
        if not self._started:
            raise RuntimeError("result recording has not started")
        if self._finished:
            raise RuntimeError("result recording has already finished")

    def _active_episode(self, episode_id: str) -> _EpisodeBuffer:
        self._require_active()
        try:
            buffer = self._episodes[episode_id]
        except KeyError as error:
            raise KeyError(f"unknown Episode ID {episode_id!r}") from error
        if buffer.complete:
            raise RuntimeError(f"Episode {episode_id!r} is already complete")
        return buffer

    def _write_metadata(self, *, complete: bool) -> None:
        assert self._started_at is not None
        atomic_write_json(
            self.experiment_directory / "metadata.json",
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "experiment_id": self.experiment_id,
                "complete": complete,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "runtime": {
                    "git_sha": self._runtime.git_sha,
                    "image_digests": dict(sorted(self._runtime.image_digests.items())),
                    "ros_distro": self._runtime.ros_distro,
                    "isaac_version": self._runtime.isaac_version,
                },
            },
        )

    def _write_summary(self, *, complete: bool) -> None:
        counts = {
            reason.name: 0
            for reason in TerminationReason
            if reason is not TerminationReason.NONE
        }
        episodes = []
        for episode_id, buffer in self._episodes.items():
            if buffer.complete:
                counts[buffer.termination_reason.name] += 1
            episodes.append(
                {
                    "episode_id": episode_id,
                    "complete": buffer.complete,
                    "termination_reason": (
                        buffer.termination_reason.name if buffer.complete else None
                    ),
                }
            )
        atomic_write_json(
            self.experiment_directory / "summary.json",
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "experiment_id": self.experiment_id,
                "complete": complete,
                "episode_count": len(episodes),
                "completed_episode_count": sum(
                    episode["complete"] for episode in episodes
                ),
                "counts": counts,
                "episodes": episodes,
            },
        )

    def _write_events(self, buffer: _EpisodeBuffer) -> None:
        lines = []
        for event in buffer.events:
            lines.append(
                json.dumps(
                    {
                        "schema_version": RESULT_SCHEMA_VERSION,
                        "experiment_id": self.experiment_id,
                        "episode_id": buffer.spec.episode_id,
                        "sequence": event.sequence,
                        "event": event.event,
                        "simulation_time_s": event.simulation_time_s,
                        "detail": event.detail,
                        "payload": event.payload,
                    },
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        atomic_write_text(
            buffer.directory / "events.jsonl",
            "" if not lines else "\n".join(lines) + "\n",
        )

    def _metrics_document(
        self,
        episode_id: str,
        metrics: EpisodeMetrics | None,
    ) -> dict[str, object]:
        base: dict[str, object] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "episode_id": episode_id,
            "complete": metrics is not None,
            "success": False,
            "elapsed_time_s": None,
            "path_length_m": None,
            "final_distance_to_goal_m": None,
            "timeout": False,
            "termination_reason": None,
            "termination_reason_code": None,
            "sample_count": 0,
        }
        if metrics is not None:
            base.update(
                success=metrics.success,
                elapsed_time_s=metrics.elapsed_time_s,
                path_length_m=metrics.path_length_m,
                final_distance_to_goal_m=metrics.final_distance_to_goal_m,
                timeout=metrics.timeout,
                termination_reason=metrics.termination_reason.name,
                termination_reason_code=int(metrics.termination_reason),
                sample_count=metrics.sample_count,
            )
        return base

    @staticmethod
    def _validate_trajectory(
        samples: tuple[TrajectoryPoint, ...],
        expected_count: int,
    ) -> None:
        if any(not isinstance(sample, TrajectoryPoint) for sample in samples):
            raise TypeError("trajectory must contain TrajectoryPoint values")
        if len(samples) != expected_count:
            raise ValueError("trajectory length must agree with metrics.sample_count")
        if any(
            current.simulation_time_s <= previous.simulation_time_s
            for previous, current in zip(samples, samples[1:], strict=False)
        ):
            raise ValueError("trajectory timestamps must be strictly increasing")
        frames = {sample.frame_id for sample in samples}
        if len(frames) > 1:
            raise ValueError("trajectory samples must use one frame")

    @staticmethod
    def _trajectory_csv(samples: tuple[TrajectoryPoint, ...]) -> str:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=_TRAJECTORY_FIELDS, lineterminator="\n")
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "simulation_time_s": format(sample.simulation_time_s, ".17g"),
                    "frame_id": sample.frame_id,
                    "x": format(sample.x, ".17g"),
                    "y": format(sample.y, ".17g"),
                    "z": format(sample.z, ".17g"),
                }
            )
        return stream.getvalue()
