# Cross-package tests

This directory is reserved for contract, cross-process, cross-container, and
end-to-end tests. Unit tests stay with their owning package.

- [`contracts/`](contracts/README.md) verifies public interfaces across
  language bindings and package boundaries.
- [`fixtures/`](fixtures/README.md) contains deterministic CPU-only mock
  components used to exercise runtime contracts.
- [`integration_mock/`](integration_mock/README.md) verifies those components
  through their public ROS graph rather than implementation internals.

Runtime protocol behavior stays with the owning `packages/rh_ros` package,
including its real ROS 2 late-join transport test. Later cross-component tests
belong under `integration_mock` rather than duplicating package-level coverage.
