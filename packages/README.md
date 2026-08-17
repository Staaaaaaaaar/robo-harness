# Platform packages

This domain contains shared RoboHarness platform and communication packages.
Packages must depend toward stable layers and must not statically depend on a
specific simulator, robot, agent, task, or evaluator implementation.

The first platform package is [`rh_interfaces`](rh_interfaces/README.md), which
owns the implementation-independent ROS wire contract. `rh_core`, `rh_ros`,
and `rh_experiment` are introduced by their roadmap PRs.
