# Platform packages

This domain contains shared RoboHarness platform and communication packages.
Packages must depend toward stable layers and must not statically depend on a
specific simulator, robot, agent, task, or evaluator implementation.

- [`rh_interfaces`](rh_interfaces/README.md) owns the implementation-independent
  ROS wire contract.
- [`rh_core`](rh_core/README.md) owns ROS-independent configuration, domain
  models, lifecycle rules, and termination policy.
- [`rh_ros`](rh_ros/README.md) owns reusable ROS runtime QoS, heartbeat,
  idempotency, deadline, sequence-filtering, and model/message adapters.

`rh_experiment` is introduced by its roadmap PR.
