# `rh_interfaces`

`rh_interfaces` is the implementation-independent ROS 2 wire contract shared
by the RoboHarness Environment, Agent, and Experiment containers. It contains
messages and services only: no nodes, transport helpers, state machines, or
simulator-specific code.

## Control-plane interfaces

| ROS name | Interface | Producer/server | Consumer/client |
|---|---|---|---|
| `/roboharness/env/status` | `ComponentStatus` | Environment | Experiment |
| `/roboharness/agent/status` | `ComponentStatus` | Agent | Experiment |
| `/roboharness/env/reset_episode` | `ResetEnv` | Environment | Experiment |
| `/roboharness/agent/reset_episode` | `ResetAgent` | Agent | Experiment |
| `/roboharness/episode/state` | `EpisodeState` | Experiment | Environment, Agent, Evaluator |
| `/roboharness/task/pointnav` | `PointNavTask` | Experiment | Environment, Agent, Evaluator |
| `/roboharness/episode/start` | `StartEpisode` | Experiment | Operator or automation |
| `/roboharness/episode/abort` | `AbortEpisode` | Experiment | Operator |
| `/roboharness/episode/result` | `EpisodeResult` | Experiment | Reporting tools |

The standard robot data plane continues to use ROS types such as
`geometry_msgs/Twist`, `nav_msgs/Odometry`, and `sensor_msgs/Imu`; this package
does not wrap those observations in a generic message.

## Contract rules

- Identifiers and request IDs are opaque non-empty strings. Validation belongs
  to the core/runtime layers rather than the generated interface classes.
- `PointNavTask.goal` and `ResetEnv.initial_pose` use the `map` frame in the MVP.
- `ResetEnv.initial_pose` is the complete 3D robot initialization pose. Its ROS
  orientation is a normalized quaternion; adapters for planar sources explicitly
  supply zero `z`, roll, and pitch before conversion.
- PointNav describes a 3D target position and does not impose a target
  orientation. A future PoseNav task must introduce explicit pose semantics
  rather than reinterpreting the PointNav goal.
- PointNav success distance is the 3D Euclidean distance in metres from the
  configured robot tracking point (MVP: the `base_link` origin) to the goal.
- Durations use seconds, distances use metres, and Episode metrics use
  simulation time and the `map` frame.
- `ComponentStatus.stamp` records the last transition time. Repeated status
  heartbeats retain it instead of replacing it with publication time.
- `EpisodeState.sequence` increases on every authoritative transition within an
  Episode. Consumers reject stale Episode IDs or sequence values.
- `EpisodeResult` is deliberately compact. `result_uri` is opaque and points to
  the durable JSON result; its storage scheme is not part of this ROS contract.
- A reset `request_id` is an idempotency key. Runtime behavior for duplicate
  requests is implemented in a later protocol-helper PR.
- Numeric state and termination values are stable wire values. New values may
  be appended, but existing values must never be reordered or reused.
- `detail`, abort `reason`, and `result_uri` are opaque strings. Correctness must
  never depend on parsing human-readable text.

QoS, deadlines, heartbeat behavior, validation, and node implementations are
intentionally outside this package.
