# Cross-package tests

This directory is reserved for contract, cross-process, cross-container, and
end-to-end tests. Unit tests stay with their owning package.

- [`contracts/`](contracts/README.md) verifies public interfaces across
  language bindings and package boundaries.
- `fixtures/` will contain deterministic CPU-only mock components in later
  roadmap PRs.
