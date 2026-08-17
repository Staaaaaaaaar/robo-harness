# Platform packages

This domain contains shared RoboHarness platform and communication packages.
Packages must depend toward stable layers and must not statically depend on a
specific simulator, robot, agent, task, or evaluator implementation.

- [`rh_interfaces`](rh_interfaces/README.md) owns the implementation-independent
  ROS wire contract.
- [`rh_core`](rh_core/README.md) owns ROS-independent configuration, domain
  models, lifecycle rules, and termination policy.

`rh_ros` and `rh_experiment` are introduced by their roadmap PRs.
