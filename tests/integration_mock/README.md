# Mock integration tests

This directory contains CPU-only black-box integration suites for the reference
Mock Environment, Mock Agent, and Experiment components. Tests interact through
the same ROS topics, services, TF, and clock used by real implementations.

- `rh_mock_env_integration_tests` verifies Environment readiness, full 3D reset,
  reset idempotency, Episode motion gating, command watchdog, clock/odom/TF, and
  controlled reset, clock-freeze, and stale-heartbeat failures.

The mock fixtures remain deterministic protocol probes; passing these tests is
not evidence of simulator physics or robot compatibility.
