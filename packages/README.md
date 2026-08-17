# Platform packages

This domain contains shared RoboHarness platform and communication packages.
Packages must depend toward stable layers and must not statically depend on a
specific simulator, robot, agent, task, or evaluator implementation.

PR 01 intentionally contains no placeholder ROS packages. `rh_interfaces`,
`rh_core`, `rh_ros`, and `rh_experiment` are introduced by their roadmap PRs.
