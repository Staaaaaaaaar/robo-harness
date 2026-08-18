# Repository tools

- `dev/` contains dependencies and thin helpers for the development environment.
- `e2e/` starts the isolated CPU mock Compose project and independently validates
  its committed three-Episode result tree.
- `validation/` contains repository-wide checks used identically by developers
  and CI.

Business logic and runtime lifecycle behavior do not belong in this directory.
