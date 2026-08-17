# Cross-package tests

This directory is reserved for contract, cross-process, cross-container, and
end-to-end tests. Unit tests stay with their owning package.

`fixtures/` will contain deterministic CPU-only mock components; it is a Colcon
base path but contains no placeholder package in PR 01.
