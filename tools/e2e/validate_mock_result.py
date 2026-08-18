#!/usr/bin/env python3
"""Validate the deterministic PR 12 mock Compose result without ROS imports."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT_FILES = {"config.yaml", "metadata.json", "summary.json", "episodes"}
EPISODE_FILES = {"episode.yaml", "events.jsonl", "trajectory.csv", "metrics.json"}
TRAJECTORY_HEADER = ["simulation_time_s", "frame_id", "x", "y", "z"]
EPISODE_IDS = ["compose-0000", "compose-0001", "compose-0002"]


class ValidationError(ValueError):
    """The result is incomplete or does not match the PR 12 contract."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot parse {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def complete_only(result_dir: Path, experiment_id: str) -> bool:
    try:
        metadata = load_json(result_dir / "metadata.json")
    except ValidationError:
        return False
    return metadata.get("experiment_id") == experiment_id and metadata.get("complete") is True


def validate(result_dir: Path, experiment_id: str) -> None:
    require(result_dir.is_dir(), f"result directory is missing: {result_dir}")
    require(
        {item.name for item in result_dir.iterdir()} == ROOT_FILES, "invalid result root layout"
    )

    metadata = load_json(result_dir / "metadata.json")
    summary = load_json(result_dir / "summary.json")
    for label, document in (("metadata", metadata), ("summary", summary)):
        require(document.get("schema_version") == 1, f"{label} schema version is not 1")
        require(document.get("experiment_id") == experiment_id, f"{label} experiment ID mismatch")
        require(document.get("complete") is True, f"{label} is not committed")

    require(summary.get("episode_count") == 3, "summary episode count must be 3")
    require(summary.get("completed_episode_count") == 3, "all Episodes must be complete")
    counts = summary.get("counts")
    require(
        isinstance(counts, dict) and counts.get("TIMEOUT") == 3, "all Episodes must end in TIMEOUT"
    )
    entries = summary.get("episodes")
    require(isinstance(entries, list), "summary episodes must be a list")
    require(
        [entry.get("episode_id") for entry in entries if isinstance(entry, dict)] == EPISODE_IDS,
        "summary Episode order mismatch",
    )
    require(
        all(
            isinstance(entry, dict)
            and entry.get("complete") is True
            and entry.get("termination_reason") == "TIMEOUT"
            for entry in entries
        ),
        "summary Episode commit state mismatch",
    )

    episodes_dir = result_dir / "episodes"
    require(
        {item.name for item in episodes_dir.iterdir()} == set(EPISODE_IDS),
        "Episode directories mismatch",
    )
    for episode_id in EPISODE_IDS:
        episode_dir = episodes_dir / episode_id
        require(
            {item.name for item in episode_dir.iterdir()} == EPISODE_FILES,
            f"{episode_id} layout mismatch",
        )
        metrics = load_json(episode_dir / "metrics.json")
        require(
            metrics.get("experiment_id") == experiment_id, f"{episode_id} experiment ID mismatch"
        )
        require(metrics.get("episode_id") == episode_id, f"{episode_id} metrics identity mismatch")
        require(metrics.get("complete") is True, f"{episode_id} metrics are incomplete")
        require(metrics.get("success") is False, f"{episode_id} must not report success")
        require(metrics.get("timeout") is True, f"{episode_id} must report timeout")
        require(metrics.get("termination_reason") == "TIMEOUT", f"{episode_id} reason mismatch")
        sample_count = metrics.get("sample_count")
        require(
            isinstance(sample_count, int) and sample_count >= 0,
            f"{episode_id} sample count is invalid",
        )

        with (episode_dir / "trajectory.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            require(
                reader.fieldnames == TRAJECTORY_HEADER, f"{episode_id} trajectory header mismatch"
            )
            rows = list(reader)
        require(len(rows) == sample_count, f"{episode_id} trajectory length mismatch")

        events_path = episode_dir / "events.jsonl"
        for sequence, line in enumerate(events_path.read_text(encoding="utf-8").splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValidationError(f"{episode_id} contains invalid event JSON") from error
            require(event.get("schema_version") == 1, f"{episode_id} event schema mismatch")
            require(
                event.get("experiment_id") == experiment_id,
                f"{episode_id} event experiment mismatch",
            )
            require(event.get("episode_id") == episode_id, f"{episode_id} event identity mismatch")
            require(
                event.get("sequence") == sequence, f"{episode_id} event sequence is not contiguous"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--complete-only", action="store_true")
    parser.add_argument("result_directory", type=Path)
    parser.add_argument("experiment_id")
    args = parser.parse_args()
    if args.complete_only:
        return 0 if complete_only(args.result_directory, args.experiment_id) else 1
    try:
        validate(args.result_directory, args.experiment_id)
    except (OSError, ValidationError) as error:
        print(f"Result validation failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated three-Episode mock result: {args.result_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
