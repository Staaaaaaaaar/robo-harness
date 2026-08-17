from pathlib import Path

import pytest

from rh_experiment.recorder.io import atomic_write_text


def test_atomic_replace_preserves_previous_file_when_commit_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "metrics.json"
    atomic_write_text(destination, "old\n")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("rh_experiment.recorder.io.os.replace", fail_replace)

    with pytest.raises(OSError, match="injected"):
        atomic_write_text(destination, "new\n")

    assert destination.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob("*.tmp")) == []
