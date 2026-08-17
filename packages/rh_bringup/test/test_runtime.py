from __future__ import annotations

from collections.abc import Callable

from rh_bringup import runtime


def test_pointnav_simple_profile_starts_generic_experiment(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_experiment_main(
        args: list[str],
        *,
        task_publisher_factory: Callable[..., object],
        evaluator_factory: Callable[..., object],
    ) -> None:
        captured.update(
            args=args,
            task_publisher_factory=task_publisher_factory,
            evaluator_factory=evaluator_factory,
        )

    monkeypatch.setattr(runtime, "experiment_main", fake_experiment_main)

    runtime.main(
        [
            "--profile",
            "pointnav_simple",
            "--ros-args",
            "-p",
            "config_path:=/workspace/config.yaml",
        ]
    )

    assembly = runtime.ASSEMBLIES["pointnav_simple"]
    assert captured == {
        "args": [
            "--ros-args",
            "-p",
            "config_path:=/workspace/config.yaml",
        ],
        "task_publisher_factory": assembly.task_publisher_factory,
        "evaluator_factory": assembly.evaluator_factory,
    }
