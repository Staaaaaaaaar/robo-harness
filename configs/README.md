# Configuration

Versioned experiment, scenario, agent, task, and simulator configuration belongs
in this domain. [`experiments/mvp.yaml`](experiments/mvp.yaml) is the canonical
schema-version 1 PointNav example validated by `rh_core`.

Episode initialization uses a complete 3D pose (`x/y/z` in metres and
`roll/pitch/yaw` in radians). PointNav goals are 3D positions without target
orientation semantics.
