from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from rh_core import ConfigError, ErrorCode, ExecutionMode
from rh_core.config import load_experiment_config, parse_experiment_config


def issue_codes(error: ConfigError) -> set[ErrorCode]:
    return {issue.code for issue in error.issues}


def test_canonical_mvp_config_loads_to_immutable_models() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    config = load_experiment_config(repository_root / "configs/experiments/mvp.yaml")

    assert config.schema_version == 1
    assert config.experiment.name == "anymal_c_keyboard_pointnav"
    assert config.experiment.execution_mode is ExecutionMode.MANUAL
    assert isinstance(config.experiment.episodes, tuple)
    assert config.experiment.episodes[0].initial_pose.frame_id == "map"
    assert config.experiment.episodes[0].initial_pose.yaw == 0.0
    assert config.experiment.episodes[0].task.goal.z == 0.4
    assert config.experiment.episodes[0].seed == 42

    with pytest.raises(FrozenInstanceError):
        config.experiment.name = "changed"  # type: ignore[misc]


def test_automatic_execution_mode_is_supported(valid_document: dict[str, Any]) -> None:
    valid_document["experiment"]["execution_mode"] = "automatic"
    config = parse_experiment_config(valid_document)
    assert config.experiment.execution_mode is ExecutionMode.AUTOMATIC


@pytest.mark.parametrize("schema_version", [0, 2, -1])
def test_unknown_schema_version_is_rejected(
    valid_document: dict[str, Any], schema_version: int
) -> None:
    valid_document["schema_version"] = schema_version
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.UNSUPPORTED_SCHEMA_VERSION in issue_codes(caught.value)


def test_missing_and_unknown_fields_are_reported_together(valid_document: dict[str, Any]) -> None:
    del valid_document["experiment"]["name"]
    valid_document["experiment"]["typo"] = True

    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)

    issues = {(issue.code, issue.path) for issue in caught.value.issues}
    assert (ErrorCode.MISSING_FIELD, "experiment.name") in issues
    assert (ErrorCode.UNKNOWN_FIELD, "experiment.typo") in issues


def test_duplicate_episode_ids_are_rejected(valid_document: dict[str, Any]) -> None:
    duplicate = deepcopy(valid_document["experiment"]["episodes"][0])
    valid_document["experiment"]["episodes"].append(duplicate)

    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)

    issue = next(
        issue for issue in caught.value.issues if issue.code is ErrorCode.DUPLICATE_EPISODE_ID
    )
    assert issue.path == "experiment.episodes[1].episode_id"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["x", "y", "z"])
def test_non_finite_goal_values_are_rejected(
    valid_document: dict[str, Any], field: str, value: float
) -> None:
    valid_document["experiment"]["episodes"][0]["task"]["goal"][field] = value
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.INVALID_VALUE in issue_codes(caught.value)


def test_unrepresentably_large_number_is_structured(valid_document: dict[str, Any]) -> None:
    valid_document["experiment"]["episodes"][0]["task"]["goal"]["x"] = 10**10000
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.INVALID_VALUE in issue_codes(caught.value)


@pytest.mark.parametrize("field", ["success_radius_m", "timeout_s"])
@pytest.mark.parametrize("value", [0, -1.0, float("nan"), float("inf")])
def test_positive_finite_task_limits_are_required(
    valid_document: dict[str, Any], field: str, value: float
) -> None:
    valid_document["experiment"]["episodes"][0]["task"][field] = value
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.INVALID_VALUE in issue_codes(caught.value)


def test_frame_mismatch_and_non_map_frames_are_reported(valid_document: dict[str, Any]) -> None:
    episode = valid_document["experiment"]["episodes"][0]
    episode["initial_pose"]["frame_id"] = "odom"

    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)

    assert ErrorCode.FRAME_MISMATCH in issue_codes(caught.value)
    assert ErrorCode.UNSUPPORTED_FRAME in issue_codes(caught.value)


@pytest.mark.parametrize("value", [True, 1.5, 2**63, -(2**63) - 1])
def test_seed_must_be_int64(valid_document: dict[str, Any], value: object) -> None:
    valid_document["experiment"]["episodes"][0]["seed"] = value
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert issue_codes(caught.value) & {ErrorCode.TYPE_MISMATCH, ErrorCode.INVALID_VALUE}


@pytest.mark.parametrize("path", ["success_radius_m", "timeout_s"])
def test_boolean_is_not_accepted_as_numeric_value(
    valid_document: dict[str, Any], path: str
) -> None:
    valid_document["experiment"]["episodes"][0]["task"][path] = True
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.TYPE_MISMATCH in issue_codes(caught.value)


def test_unsupported_task_type_is_rejected(valid_document: dict[str, Any]) -> None:
    valid_document["experiment"]["episodes"][0]["task"]["type"] = "coverage"
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.INVALID_VALUE in issue_codes(caught.value)


def test_orientation_field_is_rejected_for_pointnav(
    valid_document: dict[str, Any],
) -> None:
    valid_document["experiment"]["episodes"][0]["task"]["goal"]["yaw"] = 1.0
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert (ErrorCode.UNKNOWN_FIELD, "experiment.episodes[0].task.goal.yaw") in {
        (issue.code, issue.path) for issue in caught.value.issues
    }


@pytest.mark.parametrize("field", ["x", "y", "z", "roll", "pitch", "yaw"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_initial_pose_requires_finite_position_and_orientation(
    valid_document: dict[str, Any], field: str, value: float
) -> None:
    valid_document["experiment"]["episodes"][0]["initial_pose"][field] = value
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)
    assert ErrorCode.INVALID_VALUE in issue_codes(caught.value)


def test_root_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError) as caught:
        parse_experiment_config([])
    assert caught.value.issues[0].code is ErrorCode.TYPE_MISMATCH
    assert caught.value.issues[0].path == "$"


def test_yaml_duplicate_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_experiment_config(path)
    assert caught.value.issues[0].code is ErrorCode.YAML_DUPLICATE_KEY


def test_invalid_yaml_is_structured(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("experiment: [\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_experiment_config(path)
    assert caught.value.issues[0].code is ErrorCode.YAML_SYNTAX


def test_missing_file_is_structured(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError) as caught:
        load_experiment_config(path)
    assert caught.value.issues[0].as_dict() == {
        "code": "file_not_found",
        "path": str(path),
        "message": "configuration file does not exist",
    }


def test_duplicate_id_path_keeps_original_index_when_prior_episode_is_invalid(
    valid_document: dict[str, Any],
) -> None:
    first = deepcopy(valid_document["experiment"]["episodes"][0])
    invalid = deepcopy(first)
    invalid["episode_id"] = ""
    duplicate = deepcopy(first)
    valid_document["experiment"]["episodes"] = [first, invalid, duplicate]

    with pytest.raises(ConfigError) as caught:
        parse_experiment_config(valid_document)

    duplicate_issue = next(
        issue for issue in caught.value.issues if issue.code is ErrorCode.DUPLICATE_EPISODE_ID
    )
    assert duplicate_issue.path == "experiment.episodes[2].episode_id"
