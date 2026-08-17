# Contributing to RoboHarness

RoboHarness uses small, reviewable pull requests. The architecture and staged
roadmap in [the development plan](docs/architecture-and-development-plan.md) are
the implementation baseline.

## Development environment

The supported development path is the repository CPU development container.
The host needs Git, Docker Engine, Docker Compose v2, and Make; it does not need
a native ROS installation.

```bash
make dev-image
make dev-check
```

Use `make dev-shell` for an interactive Ubuntu 22.04 / ROS 2 Humble shell. Do
not install project dependencies globally on the host and do not use `sudo pip`.

## Branches and commits

- Do not push directly to `main`; use a pull request and required checks.
- Use short-lived `feat/<scope>`, `fix/<scope>`, `docs/<scope>`, or
  `ci/<scope>` branches.
- Use Conventional Commits such as `build(repo): add colcon defaults`.
- Prefer Squash Merge so one roadmap PR becomes one reversible commit on
  `main`.

## Pull requests

Keep a pull request focused on one roadmap item. Complete every section in the
pull request template and link the relevant PR number from the development
plan. If implementation changes a confirmed architecture decision, add an ADR
that explains compatibility and migration.

Before requesting review, run:

```bash
make dev-check
```

Build, lint, tests, documentation, and acceptance evidence must agree with the
declared scope and out-of-scope sections. Do not use placeholder packages or
stubs that appear to implement unfinished runtime behavior.
