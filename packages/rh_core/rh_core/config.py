"""Strict YAML loading and static validation for Experiment configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

from rh_core.errors import ConfigError, ErrorCode, ValidationIssue
from rh_core.models import (
    EpisodeSpec,
    ExecutionMode,
    ExperimentConfig,
    ExperimentSpec,
    Point3D,
    PointNavTaskSpec,
    Pose3D,
)

SUPPORTED_SCHEMA_VERSION = 1
MVP_FRAME_ID = "map"
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: object) -> None:
        self.key = key
        super().__init__(f"duplicate YAML mapping key: {key!r}")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects silent mapping-key replacement."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise _DuplicateKeyError(key)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class _Validator:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(self, code: ErrorCode, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(code=code, path=path, message=message))

    def mapping(
        self,
        value: object,
        path: str,
        *,
        required: frozenset[str],
        allowed: frozenset[str],
    ) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            self.add(ErrorCode.TYPE_MISMATCH, path, "expected a mapping")
            return None

        valid_keys: set[str] = set()
        for key in value:
            if not isinstance(key, str):
                self.add(
                    ErrorCode.TYPE_MISMATCH,
                    path,
                    f"mapping keys must be strings, got {type(key).__name__}",
                )
                continue
            valid_keys.add(key)
            if key not in allowed:
                self.add(ErrorCode.UNKNOWN_FIELD, f"{path}.{key}", "unknown field")

        for key in sorted(required - valid_keys):
            self.add(ErrorCode.MISSING_FIELD, f"{path}.{key}", "required field is missing")
        return value

    def string(self, value: object, path: str) -> str | None:
        if not isinstance(value, str):
            self.add(ErrorCode.TYPE_MISMATCH, path, "expected a string")
            return None
        if not value.strip():
            self.add(ErrorCode.INVALID_VALUE, path, "must not be empty")
            return None
        return value

    def number(self, value: object, path: str) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.add(ErrorCode.TYPE_MISMATCH, path, "expected a number")
            return None
        try:
            converted = float(value)
        except OverflowError:
            self.add(ErrorCode.INVALID_VALUE, path, "must be finite")
            return None
        if not math.isfinite(converted):
            self.add(ErrorCode.INVALID_VALUE, path, "must be finite")
            return None
        return converted

    def int64(self, value: object, path: str) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            self.add(ErrorCode.TYPE_MISMATCH, path, "expected an integer")
            return None
        if not _INT64_MIN <= value <= _INT64_MAX:
            self.add(ErrorCode.INVALID_VALUE, path, "must fit in a signed 64-bit integer")
            return None
        return value


def _parse_point(value: object, path: str, validator: _Validator) -> Point3D | None:
    issue_count = len(validator.issues)
    data = validator.mapping(
        value,
        path,
        required=frozenset({"frame_id", "x", "y", "z"}),
        allowed=frozenset({"frame_id", "x", "y", "z"}),
    )
    if data is None:
        return None

    frame_id = (
        validator.string(data["frame_id"], f"{path}.frame_id")
        if "frame_id" in data
        else None
    )
    x = validator.number(data["x"], f"{path}.x") if "x" in data else None
    y = validator.number(data["y"], f"{path}.y") if "y" in data else None
    z = validator.number(data["z"], f"{path}.z") if "z" in data else None

    if len(validator.issues) != issue_count:
        return None
    assert frame_id is not None and x is not None and y is not None and z is not None
    return Point3D(frame_id=frame_id, x=x, y=y, z=z)


def _parse_pose(value: object, path: str, validator: _Validator) -> Pose3D | None:
    issue_count = len(validator.issues)
    fields = frozenset({"frame_id", "x", "y", "z", "roll", "pitch", "yaw"})
    data = validator.mapping(value, path, required=fields, allowed=fields)
    if data is None:
        return None

    frame_id = (
        validator.string(data["frame_id"], f"{path}.frame_id")
        if "frame_id" in data
        else None
    )
    x = validator.number(data["x"], f"{path}.x") if "x" in data else None
    y = validator.number(data["y"], f"{path}.y") if "y" in data else None
    z = validator.number(data["z"], f"{path}.z") if "z" in data else None
    roll = validator.number(data["roll"], f"{path}.roll") if "roll" in data else None
    pitch = (
        validator.number(data["pitch"], f"{path}.pitch") if "pitch" in data else None
    )
    yaw = validator.number(data["yaw"], f"{path}.yaw") if "yaw" in data else None

    if len(validator.issues) != issue_count:
        return None
    assert (
        frame_id is not None
        and x is not None
        and y is not None
        and z is not None
        and roll is not None
        and pitch is not None
        and yaw is not None
    )
    return Pose3D(
        frame_id=frame_id,
        x=x,
        y=y,
        z=z,
        roll=roll,
        pitch=pitch,
        yaw=yaw,
    )


def _parse_task(
    value: object,
    path: str,
    validator: _Validator,
) -> PointNavTaskSpec | None:
    issue_count = len(validator.issues)
    fields = frozenset({"type", "goal", "success_radius_m", "timeout_s"})
    data = validator.mapping(value, path, required=fields, allowed=fields)
    if data is None:
        return None

    task_type = validator.string(data["type"], f"{path}.type") if "type" in data else None
    if task_type is not None and task_type != "pointnav":
        validator.add(ErrorCode.INVALID_VALUE, f"{path}.type", "only 'pointnav' is supported")

    goal = _parse_point(data["goal"], f"{path}.goal", validator) if "goal" in data else None
    radius = (
        validator.number(data["success_radius_m"], f"{path}.success_radius_m")
        if "success_radius_m" in data
        else None
    )
    timeout = (
        validator.number(data["timeout_s"], f"{path}.timeout_s")
        if "timeout_s" in data
        else None
    )

    if radius is not None and radius <= 0.0:
        validator.add(
            ErrorCode.INVALID_VALUE,
            f"{path}.success_radius_m",
            "must be greater than zero",
        )
    if timeout is not None and timeout <= 0.0:
        validator.add(ErrorCode.INVALID_VALUE, f"{path}.timeout_s", "must be greater than zero")

    if goal is not None:
        if goal.frame_id != MVP_FRAME_ID:
            validator.add(
                ErrorCode.UNSUPPORTED_FRAME,
                f"{path}.goal.frame_id",
                f"MVP requires frame_id '{MVP_FRAME_ID}'",
            )

    if len(validator.issues) != issue_count:
        return None
    assert goal is not None and radius is not None and timeout is not None
    return PointNavTaskSpec(
        goal=goal,
        success_radius_m=radius,
        timeout_s=timeout,
    )


def _parse_episode(value: object, index: int, validator: _Validator) -> EpisodeSpec | None:
    path = f"experiment.episodes[{index}]"
    issue_count = len(validator.issues)
    fields = frozenset({"episode_id", "scenario", "initial_pose", "task", "seed"})
    data = validator.mapping(value, path, required=fields, allowed=fields)
    if data is None:
        return None

    episode_id = (
        validator.string(data["episode_id"], f"{path}.episode_id")
        if "episode_id" in data
        else None
    )
    scenario = (
        validator.string(data["scenario"], f"{path}.scenario")
        if "scenario" in data
        else None
    )
    initial_pose = (
        _parse_pose(data["initial_pose"], f"{path}.initial_pose", validator)
        if "initial_pose" in data
        else None
    )
    task = _parse_task(data["task"], f"{path}.task", validator) if "task" in data else None
    seed = validator.int64(data["seed"], f"{path}.seed") if "seed" in data else None

    if len(validator.issues) != issue_count:
        return None
    if initial_pose is not None:
        if initial_pose.frame_id != MVP_FRAME_ID:
            validator.add(
                ErrorCode.UNSUPPORTED_FRAME,
                f"{path}.initial_pose.frame_id",
                f"MVP requires frame_id '{MVP_FRAME_ID}'",
            )
        if task is not None and initial_pose.frame_id != task.goal.frame_id:
            validator.add(
                ErrorCode.FRAME_MISMATCH,
                path,
                "initial_pose and task goal frame_id values must match",
            )

    if len(validator.issues) != issue_count:
        return None
    assert (
        episode_id is not None
        and scenario is not None
        and initial_pose is not None
        and task is not None
        and seed is not None
    )
    return EpisodeSpec(
        episode_id=episode_id,
        scenario=scenario,
        initial_pose=initial_pose,
        task=task,
        seed=seed,
    )


def _parse_experiment(value: object, validator: _Validator) -> ExperimentSpec | None:
    path = "experiment"
    issue_count = len(validator.issues)
    fields = frozenset({"name", "execution_mode", "episodes"})
    data = validator.mapping(value, path, required=fields, allowed=fields)
    if data is None:
        return None

    name = validator.string(data["name"], f"{path}.name") if "name" in data else None

    mode_value = (
        validator.string(data["execution_mode"], f"{path}.execution_mode")
        if "execution_mode" in data
        else None
    )
    mode: ExecutionMode | None = None
    if mode_value is not None:
        try:
            mode = ExecutionMode(mode_value)
        except ValueError:
            validator.add(
                ErrorCode.INVALID_VALUE,
                f"{path}.execution_mode",
                "must be 'manual' or 'automatic'",
            )

    indexed_episodes: list[tuple[int, EpisodeSpec]] = []
    raw_episodes = data.get("episodes")
    if "episodes" in data:
        if not isinstance(raw_episodes, list):
            validator.add(ErrorCode.TYPE_MISMATCH, f"{path}.episodes", "expected a list")
        elif not raw_episodes:
            validator.add(ErrorCode.INVALID_VALUE, f"{path}.episodes", "must not be empty")
        else:
            for index, raw_episode in enumerate(raw_episodes):
                episode = _parse_episode(raw_episode, index, validator)
                if episode is not None:
                    indexed_episodes.append((index, episode))

    first_index_by_id: dict[str, int] = {}
    for source_index, episode in indexed_episodes:
        first_index = first_index_by_id.setdefault(episode.episode_id, source_index)
        if first_index != source_index:
            validator.add(
                ErrorCode.DUPLICATE_EPISODE_ID,
                f"{path}.episodes[{source_index}].episode_id",
                f"duplicates experiment.episodes[{first_index}].episode_id",
            )

    if len(validator.issues) != issue_count:
        return None
    assert name is not None and mode is not None and indexed_episodes
    episodes = tuple(episode for _, episode in indexed_episodes)
    return ExperimentSpec(name=name, execution_mode=mode, episodes=episodes)


def parse_experiment_config(document: object) -> ExperimentConfig:
    """Validate a decoded YAML document and return immutable typed models."""

    validator = _Validator()
    fields = frozenset({"schema_version", "experiment"})
    root = validator.mapping(document, "$", required=fields, allowed=fields)
    if root is None:
        raise ConfigError(validator.issues)

    schema_version = (
        validator.int64(root["schema_version"], "schema_version")
        if "schema_version" in root
        else None
    )
    if schema_version is not None and schema_version != SUPPORTED_SCHEMA_VERSION:
        validator.add(
            ErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            "schema_version",
            f"supported version is {SUPPORTED_SCHEMA_VERSION}",
        )

    experiment = (
        _parse_experiment(root["experiment"], validator) if "experiment" in root else None
    )

    if validator.issues:
        raise ConfigError(validator.issues)
    assert schema_version is not None and experiment is not None
    return ExperimentConfig(schema_version=schema_version, experiment=experiment)


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """Load one UTF-8 YAML file and return a validated immutable configuration."""

    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(
            (
                ValidationIssue(
                    code=ErrorCode.FILE_NOT_FOUND,
                    path=str(config_path),
                    message="configuration file does not exist",
                ),
            )
        ) from exc
    except OSError as exc:
        raise ConfigError(
            (
                ValidationIssue(
                    code=ErrorCode.FILE_READ_ERROR,
                    path=str(config_path),
                    message=str(exc),
                ),
            )
        ) from exc

    try:
        document = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except _DuplicateKeyError as exc:
        raise ConfigError(
            (
                ValidationIssue(
                    code=ErrorCode.YAML_DUPLICATE_KEY,
                    path=str(config_path),
                    message=f"duplicate mapping key {exc.key!r}",
                ),
            )
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            (
                ValidationIssue(
                    code=ErrorCode.YAML_SYNTAX,
                    path=str(config_path),
                    message=str(exc),
                ),
            )
        ) from exc

    return parse_experiment_config(document)
