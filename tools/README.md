# Repository tools

- `dev/` contains dependencies and thin host-side helpers for the development
  environment, including the foreground Isaac GUI launcher with scoped X11
  access and cleanup.
- `e2e/` starts the isolated CPU mock Compose project and independently validates
  its committed three-Episode result tree. It also contains the manual PR 13
  GPU/ROS 2 Bridge smoke harness and evidence collector.
- `validation/` contains repository-wide checks used identically by developers
  and CI, including dependency-light checks for the Isaac image pin, Kit app,
  extension declaration, and native clock graph.

Business logic and runtime lifecycle behavior do not belong in this directory.
