# Configuration

Versioned experiment, scenario, agent, task, and simulator configuration belongs
in this domain. [`experiments/mvp.yaml`](experiments/mvp.yaml) is the canonical
schema-version 1 PointNav example validated by `rh_core`.

Episode initialization uses a complete 3D pose (`x/y/z` in metres and
`roll/pitch/yaw` in radians). PointNav goals are 3D positions without target
orientation semantics.

PR 08 validates the `task.type: pointnav` section through `rh_pointnav` before
the orchestrator starts component coordination. The canonical example remains
the single source of truth rather than duplicating task-only YAML fragments.

[`experiments/mock_compose.yaml`](experiments/mock_compose.yaml) is the bounded
automatic profile used by the PR 12 CPU runtime smoke test. Its three far-away
goals intentionally produce deterministic `TIMEOUT` results with the reference
mock Agent; it is validation input, not the canonical user-facing example.
