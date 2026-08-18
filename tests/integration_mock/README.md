# Mock integration tests

This directory contains CPU-only black-box integration suites for the reference
Mock Environment, Mock Agent, and Experiment components. Tests interact through
the same ROS topics, services, TF, and clock used by real implementations.

- `rh_mock_env_integration_tests` verifies Environment readiness, full 3D reset,
  reset idempotency, Episode motion gating, command watchdog, clock/odom/TF, and
  controlled reset, clock-freeze, and stale-heartbeat failures.
- `rh_mock_agent_integration_tests` independently drives the Agent with
  test-owned task, Episode state, and simulation-clock publishers to verify
  command gating, Episode isolation, and controlled failure behavior.
- `rh_experiment_integration_tests` uses protocol-only Env and Agent stubs to
  verify the authoritative lifecycle, three-Episode process reuse, independent
  artifacts, stale-callback isolation, continue policy, and infrastructure
  stop policy.
- `rh_pointnav_integration_tests` verifies direct immutable task delivery,
  transient-local late join, and the reset/task/READY preparation order.
- `rh_simple_navigation_integration_tests` verifies fixed-trajectory metrics,
  Agent completion plus ground-truth confirmation, goal pass-through behavior,
  evaluator-to-orchestrator termination, no control publisher, and frozen-clock
  failure handling.

The mock fixtures remain deterministic protocol probes; passing these tests is
not evidence of simulator physics or robot compatibility.
