"""Independent reader and validator for result schema version 1."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from rh_core import ConfigError, TerminationReason, parse_experiment_config
from rh_experiment.recorder.paths import safe_path_component
from rh_experiment.recorder.schema import RESULT_SCHEMA_VERSION

_ROOT_FILES = frozenset({"config.yaml", "metadata.json", "summary.json", "episodes"})
_EPISODE_FILES = frozenset(
    {"episode.yaml", "events.jsonl", "trajectory.csv", "metrics.json"}
)
_TRAJECTORY_FIELDS = ["simulation_time_s", "frame_id", "x", "y", "z"]


class ResultValidationError(ValueError):
    """A result tree does not conform to its declared schema version."""


@dataclass(frozen=True, slots=True)
class ValidatedEpisodeResult:
    episode_id: str
    specification: dict[str, Any]
    metrics: dict[str, Any]
    trajectory: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ValidatedExperimentResult:
    directory: Path
    config: dict[str, Any]
    metadata: dict[str, Any]
    summary: dict[str, Any]
    episodes: tuple[ValidatedEpisodeResult, ...]


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ResultValidationError(f"{label} must be a string-keyed object")
    return value


def _required(document: dict[str, Any], keys: set[str], label: str) -> None:
    missing = keys - document.keys()
    if missing:
        raise ResultValidationError(f"{label} is missing fields: {sorted(missing)}")


def _schema(document: dict[str, Any], label: str) -> None:
    if document.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ResultValidationError(
            f"{label} schema_version must be {RESULT_SCHEMA_VERSION}"
        )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as error:
        raise ResultValidationError(f"cannot parse JSON artifact {path}: {error}") from error


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except (OSError, yaml.YAMLError) as error:
        raise ResultValidationError(f"cannot parse YAML artifact {path}: {error}") from error


def _validate_identity(
    document: dict[str, Any],
    experiment_id: str,
    label: str,
    *,
    episode_id: str | None = None,
) -> None:
    if document.get("experiment_id") != experiment_id:
        raise ResultValidationError(f"{label} experiment_id does not match metadata")
    if episode_id is not None and document.get("episode_id") != episode_id:
        raise ResultValidationError(f"{label} episode_id does not match summary")


def _validate_timestamp(value: object, label: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str):
        raise ResultValidationError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResultValidationError(f"{label} is not a valid timestamp") from error
    if parsed.tzinfo is None:
        raise ResultValidationError(f"{label} must include a timezone")


def _validate_metadata(document: dict[str, Any]) -> str:
    _schema(document, "metadata.json")
    _required(
        document,
        {"experiment_id", "complete", "started_at", "finished_at", "runtime"},
        "metadata.json",
    )
    experiment_id = document["experiment_id"]
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ResultValidationError("metadata experiment_id must be non-empty")
    if not isinstance(document["complete"], bool):
        raise ResultValidationError("metadata complete must be a bool")
    _validate_timestamp(document["started_at"], "metadata started_at")
    _validate_timestamp(
        document["finished_at"],
        "metadata finished_at",
        optional=True,
    )
    runtime = _mapping(document["runtime"], "metadata runtime")
    _required(
        runtime,
        {"git_sha", "image_digests", "ros_distro", "isaac_version"},
        "metadata runtime",
    )
    _mapping(runtime["image_digests"], "metadata image_digests")
    return experiment_id


def _validate_metrics(
    document: dict[str, Any],
    experiment_id: str,
    episode_id: str,
) -> None:
    _schema(document, "metrics.json")
    _required(
        document,
        {
            "experiment_id",
            "episode_id",
            "complete",
            "success",
            "elapsed_time_s",
            "path_length_m",
            "final_distance_to_goal_m",
            "timeout",
            "termination_reason",
            "termination_reason_code",
            "sample_count",
        },
        "metrics.json",
    )
    _validate_identity(
        document,
        experiment_id,
        "metrics.json",
        episode_id=episode_id,
    )
    if not isinstance(document["complete"], bool):
        raise ResultValidationError("metrics complete must be a bool")
    if not isinstance(document["sample_count"], int) or document["sample_count"] < 0:
        raise ResultValidationError("metrics sample_count must be non-negative")
    if not document["complete"]:
        if document["termination_reason"] is not None:
            raise ResultValidationError("incomplete metrics must not have a reason")
        return
    try:
        reason = TerminationReason[document["termination_reason"]]
    except (KeyError, TypeError) as error:
        raise ResultValidationError("metrics termination_reason is invalid") from error
    if int(reason) != document["termination_reason_code"]:
        raise ResultValidationError("termination reason name and code disagree")
    if document["success"] != (reason is TerminationReason.SUCCESS):
        raise ResultValidationError("metrics success disagrees with termination reason")
    if document["timeout"] != (reason is TerminationReason.TIMEOUT):
        raise ResultValidationError("metrics timeout disagrees with termination reason")
    for field in ("elapsed_time_s", "path_length_m"):
        value = document[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value < 0.0
        ):
            raise ResultValidationError(f"metrics {field} must be non-negative")
    final_distance = document["final_distance_to_goal_m"]
    if final_distance is not None and (
        isinstance(final_distance, bool)
        or not isinstance(final_distance, int | float)
        or not math.isfinite(final_distance)
        or final_distance < 0.0
    ):
        raise ResultValidationError("metrics final distance must be non-negative or null")


def _read_trajectory(
    path: Path,
    expected_count: int | None,
) -> tuple[dict[str, Any], ...]:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != _TRAJECTORY_FIELDS:
                raise ResultValidationError("trajectory.csv has an invalid header")
            rows = tuple(dict(row) for row in reader)
    except OSError as error:
        raise ResultValidationError(f"cannot read trajectory.csv: {error}") from error
    if expected_count is not None and len(rows) != expected_count:
        raise ResultValidationError("trajectory length disagrees with metrics")
    last_time: float | None = None
    for row in rows:
        if not row["frame_id"]:
            raise ResultValidationError("trajectory frame_id must be non-empty")
        try:
            timestamp = float(row["simulation_time_s"])
            values = tuple(float(row[field]) for field in ("x", "y", "z"))
        except (TypeError, ValueError) as error:
            raise ResultValidationError("trajectory contains a non-numeric value") from error
        if not math.isfinite(timestamp) or timestamp < 0.0:
            raise ResultValidationError("trajectory timestamp must be non-negative")
        if not all(math.isfinite(value) for value in values):
            raise ResultValidationError("trajectory position must be finite")
        if last_time is not None and timestamp <= last_time:
            raise ResultValidationError("trajectory timestamps must strictly increase")
        last_time = timestamp
    return rows


def _read_events(
    path: Path,
    experiment_id: str,
    episode_id: str,
) -> tuple[dict[str, Any], ...]:
    events = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ResultValidationError(f"cannot read events.jsonl: {error}") from error
    for sequence, line in enumerate(lines):
        try:
            event = _mapping(json.loads(line), "events.jsonl line")
        except json.JSONDecodeError as error:
            raise ResultValidationError("events.jsonl contains invalid JSON") from error
        _schema(event, "events.jsonl event")
        _validate_identity(
            event,
            experiment_id,
            "events.jsonl event",
            episode_id=episode_id,
        )
        if event.get("sequence") != sequence:
            raise ResultValidationError("event sequences must be contiguous")
        if not isinstance(event.get("event"), str) or not event["event"].strip():
            raise ResultValidationError("event name must be non-empty")
        events.append(event)
    return tuple(events)


def validate_result_tree(path: str | Path) -> ValidatedExperimentResult:
    """Parse and validate one complete or interrupted v1 result tree."""

    directory = Path(path)
    if not directory.is_dir():
        raise ResultValidationError(f"result directory does not exist: {directory}")
    if {item.name for item in directory.iterdir()} != _ROOT_FILES:
        raise ResultValidationError("result root does not match the v1 layout")

    config = _load_yaml(directory / "config.yaml")
    _schema(config, "config.yaml")
    try:
        parse_experiment_config(config)
    except ConfigError as error:
        raise ResultValidationError("config.yaml is not a valid Experiment config") from error
    configured_episodes = {
        episode["episode_id"]: episode
        for episode in config["experiment"]["episodes"]
    }
    metadata = _load_json(directory / "metadata.json")
    experiment_id = _validate_metadata(metadata)
    summary = _load_json(directory / "summary.json")
    _schema(summary, "summary.json")
    _validate_identity(summary, experiment_id, "summary.json")
    _required(
        summary,
        {
            "complete",
            "episode_count",
            "completed_episode_count",
            "counts",
            "episodes",
        },
        "summary.json",
    )
    if not isinstance(summary["complete"], bool):
        raise ResultValidationError("summary complete must be a bool")
    if metadata["complete"] and not summary["complete"]:
        raise ResultValidationError("committed metadata requires a complete summary")
    episode_entries = summary["episodes"]
    if not isinstance(episode_entries, list):
        raise ResultValidationError("summary episodes must be a list")
    if summary["episode_count"] != len(episode_entries):
        raise ResultValidationError("summary episode_count is inconsistent")

    episodes_directory = directory / "episodes"
    expected_directories: set[str] = set()
    episodes = []
    calculated_counts = {
        reason.name: 0
        for reason in TerminationReason
        if reason is not TerminationReason.NONE
    }
    completed_count = 0
    for entry_value in episode_entries:
        entry = _mapping(entry_value, "summary episode")
        _required(
            entry,
            {"episode_id", "complete", "termination_reason"},
            "summary episode",
        )
        episode_id = entry["episode_id"]
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise ResultValidationError("summary episode_id must be non-empty")
        encoded_id = safe_path_component(episode_id)
        if encoded_id in expected_directories:
            raise ResultValidationError("summary contains duplicate Episode IDs")
        expected_directories.add(encoded_id)
        episode_directory = episodes_directory / encoded_id
        if not episode_directory.is_dir() or {
            item.name for item in episode_directory.iterdir()
        } != _EPISODE_FILES:
            raise ResultValidationError("Episode directory does not match v1 layout")
        specification = _load_yaml(episode_directory / "episode.yaml")
        _schema(specification, "episode.yaml")
        _validate_identity(specification, experiment_id, "episode.yaml")
        episode_spec = _mapping(specification.get("episode"), "episode.yaml episode")
        if episode_spec.get("episode_id") != episode_id:
            raise ResultValidationError("episode.yaml ID does not match summary")
        if configured_episodes.get(episode_id) != episode_spec:
            raise ResultValidationError("episode.yaml does not match config.yaml")
        metrics = _load_json(episode_directory / "metrics.json")
        _validate_metrics(metrics, experiment_id, episode_id)
        if metadata["complete"]:
            if entry["complete"] != metrics["complete"]:
                raise ResultValidationError("summary and metrics completeness disagree")
            if entry["termination_reason"] != metrics["termination_reason"]:
                raise ResultValidationError("summary and metrics reason disagree")
        if metrics["complete"]:
            completed_count += 1
            calculated_counts[metrics["termination_reason"]] += 1
        trajectory = _read_trajectory(
            episode_directory / "trajectory.csv",
            metrics["sample_count"] if metrics["complete"] else None,
        )
        events = _read_events(
            episode_directory / "events.jsonl",
            experiment_id,
            episode_id,
        )
        episodes.append(
            ValidatedEpisodeResult(
                episode_id=episode_id,
                specification=specification,
                metrics=metrics,
                trajectory=trajectory,
                events=events,
            )
        )

    actual_directories = {item.name for item in episodes_directory.iterdir()}
    if actual_directories != expected_directories:
        raise ResultValidationError("episodes directory and summary disagree")
    if metadata["complete"]:
        if summary["completed_episode_count"] != completed_count:
            raise ResultValidationError("summary completed_episode_count is inconsistent")
        if summary["counts"] != calculated_counts:
            raise ResultValidationError("summary termination counts are inconsistent")
        if completed_count != len(episodes):
            raise ResultValidationError("complete Experiment contains an open Episode")

    return ValidatedExperimentResult(
        directory=directory,
        config=config,
        metadata=metadata,
        summary=summary,
        episodes=tuple(episodes),
    )
