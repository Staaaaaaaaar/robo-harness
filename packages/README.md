# Platform packages

This domain contains shared RoboHarness platform and communication packages.
Platform packages depend toward stable layers and do not statically depend on a
specific simulator, robot, agent, task, or evaluator implementation. The sole
exception is the deliberately concrete `rh_bringup` composition root.

- [`rh_interfaces`](rh_interfaces/README.md) owns the implementation-independent
  ROS wire contract.
- [`rh_core`](rh_core/README.md) owns ROS-independent configuration, domain
  models, lifecycle rules, and termination policy.
- [`rh_ros`](rh_ros/README.md) owns reusable ROS runtime QoS, heartbeat,
  idempotency, deadline, sequence-filtering, and model/message adapters.

- [`rh_experiment`](rh_experiment/README.md) owns the Experiment control plane
  and authoritative serial multi-Episode lifecycle, failure policy, and durable
  result coordination.
- [`rh_bringup`](rh_bringup/README.md) is the Experiment-container composition
  root that explicitly selects concrete Task and Evaluator implementations.
