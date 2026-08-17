from __future__ import annotations

import json
from datetime import datetime, timezone
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
    ResultValidationError,
    validate_result_tree,
)


def _record_result(tmp_path: Path) -> Path:
    episode = EpisodeSpec(
        "episode-1",
        "warehouse",
        Pose3D("map", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        PointNavTaskSpec(Point3D("map", 1.0, 0.0, 0.0), 0.2, 10.0),
        1,
    )
    config = ExperimentConfig(
        1,
        ExperimentSpec("config-name", ExecutionMode.AUTOMATIC, (episode,)),
    )
    recorder = ResultRecorder(
        tmp_path,
        "experiment-1",
        config,
        now=lambda: datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    directory = recorder.start()
    recorder.begin_episode(episode)
    recorder.complete_episode(
        episode.episode_id,
        EpisodeMetrics(
            success=False,
            elapsed_time_s=10.0,
            path_length_m=0.0,
            final_distance_to_goal_m=None,
            timeout=True,
            termination_reason=TerminationReason.TIMEOUT,
            sample_count=0,
        ),
        (),
    )
    recorder.finish()
    return directory


def test_reader_rejects_reason_code_mismatch(tmp_path: Path) -> None:
    directory = _record_result(tmp_path)
    metrics_path = directory / "episodes" / "episode-1" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["termination_reason_code"] = int(TerminationReason.SUCCESS)
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

    with pytest.raises(ResultValidationError, match="name and code"):
        validate_result_tree(directory)


def test_reader_rejects_untracked_artifact(tmp_path: Path) -> None:
    directory = _record_result(tmp_path)
    (directory / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ResultValidationError, match="v1 layout"):
        validate_result_tree(directory)
