from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rh_core import (
    EpisodeSpec,
    ExecutionMode,
    ExperimentConfig,
    ExperimentSpec,
    Point3D,
    PointNavTaskSpec,
    Pose3D,
    TerminationReason,
)
from rh_experiment.recorder import (
    EpisodeMetrics,
    ResultRecorder,
    RuntimeMetadata,
    TrajectoryPoint,
    safe_path_component,
    validate_result_tree,
)
from rh_experiment.recorder import recorder as recorder_module


def _episode(episode_id: str = "episode-1") -> EpisodeSpec:
    return EpisodeSpec(
        episode_id=episode_id,
        scenario="warehouse",
        initial_pose=Pose3D("map", 0.0, 0.0, 0.4, 0.0, 0.0, 0.0),
        task=PointNavTaskSpec(
            goal=Point3D("map", 3.0, 4.0, 0.4),
            success_radius_m=0.5,
            timeout_s=30.0,
        ),
        seed=42,
    )


def _config(episode: EpisodeSpec | None = None) -> ExperimentConfig:
    selected = episode or _episode()
    return ExperimentConfig(
        schema_version=1,
        experiment=ExperimentSpec(
            name="experiment-config",
            execution_mode=ExecutionMode.AUTOMATIC,
            episodes=(selected,),
        ),
    )


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        result = self.value
        self.value += timedelta(seconds=1)
        return result


def _success_metrics() -> EpisodeMetrics:
    return EpisodeMetrics(
        success=True,
        elapsed_time_s=2.0,
        path_length_m=5.0,
        final_distance_to_goal_m=0.1,
        timeout=False,
        termination_reason=TerminationReason.SUCCESS,
        sample_count=2,
    )


def _trajectory() -> tuple[TrajectoryPoint, ...]:
    return (
        TrajectoryPoint(10.0, "map", 0.0, 0.0, 0.4),
        TrajectoryPoint(12.0, "map", 3.0, 4.0, 0.4),
    )


def test_records_and_independently_validates_exact_v1_layout(tmp_path: Path) -> None:
    episode = _episode()
    recorder = ResultRecorder(
        tmp_path / "results",
        "experiment-1",
        _config(episode),
        runtime=RuntimeMetadata(
            git_sha="abc123",
            image_digests={"experiment": "sha256:1234"},
            ros_distro="humble",
        ),
        now=_Clock(),
    )

    result_directory = recorder.start()
    episode_directory = recorder.begin_episode(episode)
    event = recorder.record_event(
        episode.episode_id,
        "agent_succeeded",
        simulation_time_s=12.0,
        detail="Agent stopped at goal",
        payload={"source": "agent"},
    )
    result_uri = recorder.complete_episode(
        episode.episode_id,
        _success_metrics(),
        _trajectory(),
    )
    recorder.finish()

    assert event.sequence == 0
    assert result_uri == (episode_directory / "metrics.json").resolve().as_uri()
    assert {path.name for path in result_directory.iterdir()} == {
        "config.yaml",
        "metadata.json",
        "summary.json",
        "episodes",
    }
    assert {path.name for path in episode_directory.iterdir()} == {
        "episode.yaml",
        "events.jsonl",
        "trajectory.csv",
        "metrics.json",
    }

    validated = validate_result_tree(result_directory)
    assert validated.metadata["complete"] is True
    assert validated.metadata["runtime"]["git_sha"] == "abc123"
    assert validated.summary["counts"]["SUCCESS"] == 1
    assert validated.summary["completed_episode_count"] == 1
    assert validated.episodes[0].metrics["sample_count"] == 2
    assert validated.episodes[0].events[0]["event"] == "agent_succeeded"
    assert len(validated.episodes[0].trajectory) == 2


def test_interrupted_episode_remains_parseable_and_incomplete(tmp_path: Path) -> None:
    episode = _episode()
    recorder = ResultRecorder(
        tmp_path,
        "experiment-interrupted",
        _config(episode),
        now=_Clock(),
    )
    result_directory = recorder.start()
    recorder.begin_episode(episode)
    recorder.record_event(episode.episode_id, "episode_started")

    interrupted = validate_result_tree(result_directory)

    assert interrupted.metadata["complete"] is False
    assert interrupted.metadata["finished_at"] is None
    assert interrupted.summary["completed_episode_count"] == 0
    assert interrupted.episodes[0].metrics["complete"] is False
    assert interrupted.episodes[0].trajectory == ()
    assert len(interrupted.episodes[0].events) == 1

    recorder.finish(complete=False)
    finalized_failure = validate_result_tree(result_directory)
    assert finalized_failure.metadata["complete"] is False
    assert finalized_failure.metadata["finished_at"] is not None


def test_opaque_ids_are_encoded_without_path_traversal(tmp_path: Path) -> None:
    episode = _episode("../../episode/危险")
    experiment_id = "../outside/experiment"
    recorder = ResultRecorder(tmp_path, experiment_id, _config(episode), now=_Clock())

    result_directory = recorder.start()
    episode_directory = recorder.begin_episode(episode)

    assert result_directory.parent == tmp_path
    assert result_directory.name == safe_path_component(experiment_id)
    assert episode_directory.parent == result_directory / "episodes"
    assert episode_directory.name == safe_path_component(episode.episode_id)
    assert ".." not in result_directory.name
    assert "/" not in episode_directory.name
    validate_result_tree(result_directory)


def test_refuses_overwrite_and_inconsistent_completion(tmp_path: Path) -> None:
    episode = _episode()
    first = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    first.start()

    with pytest.raises(FileExistsError):
        ResultRecorder(
            tmp_path,
            "experiment-1",
            _config(episode),
            now=_Clock(),
        ).start()
    with pytest.raises(RuntimeError, match="open Episodes"):
        first.begin_episode(episode)
        first.finish()


def test_metrics_and_trajectory_invariants_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="success"):
        EpisodeMetrics(
            success=False,
            elapsed_time_s=1.0,
            path_length_m=1.0,
            final_distance_to_goal_m=0.0,
            timeout=False,
            termination_reason=TerminationReason.SUCCESS,
            sample_count=1,
        )

    episode = _episode()
    recorder = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    recorder.start()
    recorder.begin_episode(episode)
    with pytest.raises(ValueError, match="length"):
        recorder.complete_episode(episode.episode_id, _success_metrics(), ())


def test_result_documents_never_emit_nonstandard_nan(tmp_path: Path) -> None:
    episode = _episode()
    recorder = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    directory = recorder.start()
    recorder.begin_episode(episode)

    for path in directory.rglob("*.json"):
        assert "NaN" not in path.read_text(encoding="utf-8")
        json.loads(path.read_text(encoding="utf-8"))


def test_failed_metrics_commit_leaves_parseable_incomplete_episode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = _episode()
    recorder = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    directory = recorder.start()
    recorder.begin_episode(episode)
    original_write = recorder_module.atomic_write_json

    def fail_complete_metrics(path: Path, document: dict[str, object]) -> None:
        if path.name == "metrics.json" and document["complete"] is True:
            raise OSError("injected metrics commit failure")
        original_write(path, document)

    monkeypatch.setattr(recorder_module, "atomic_write_json", fail_complete_metrics)
    with pytest.raises(OSError, match="injected"):
        recorder.complete_episode(
            episode.episode_id,
            _success_metrics(),
            _trajectory(),
        )

    interrupted = validate_result_tree(directory)
    assert interrupted.metadata["complete"] is False
    assert interrupted.episodes[0].metrics["complete"] is False
    assert len(interrupted.episodes[0].trajectory) == 2


def test_failed_summary_refresh_leaves_metrics_as_episode_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = _episode()
    recorder = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    directory = recorder.start()
    recorder.begin_episode(episode)
    original_write = recorder_module.atomic_write_json

    def fail_summary(path: Path, document: dict[str, object]) -> None:
        if path.name == "summary.json":
            raise OSError("injected summary failure")
        original_write(path, document)

    monkeypatch.setattr(recorder_module, "atomic_write_json", fail_summary)
    with pytest.raises(OSError, match="injected"):
        recorder.complete_episode(
            episode.episode_id,
            _success_metrics(),
            _trajectory(),
        )

    interrupted = validate_result_tree(directory)
    assert interrupted.metadata["complete"] is False
    assert interrupted.summary["completed_episode_count"] == 0
    assert interrupted.episodes[0].metrics["complete"] is True


def test_failed_experiment_commit_keeps_metadata_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = _episode()
    recorder = ResultRecorder(tmp_path, "experiment-1", _config(episode), now=_Clock())
    directory = recorder.start()
    recorder.begin_episode(episode)
    recorder.complete_episode(episode.episode_id, _success_metrics(), _trajectory())
    original_write = recorder_module.atomic_write_json

    def fail_complete_metadata(path: Path, document: dict[str, object]) -> None:
        if path.name == "metadata.json" and document["complete"] is True:
            raise OSError("injected metadata commit failure")
        original_write(path, document)

    monkeypatch.setattr(recorder_module, "atomic_write_json", fail_complete_metadata)
    with pytest.raises(OSError, match="injected"):
        recorder.finish()

    interrupted = validate_result_tree(directory)
    assert interrupted.metadata["complete"] is False
    assert interrupted.summary["complete"] is True
