# `rh_ros`

`rh_ros` is the reusable ROS 2 runtime protocol layer between the
ROS-independent `rh_core` domain and the `rh_interfaces` wire contract. It
standardizes transport behavior that Environment, Agent, Evaluator, and
Experiment components would otherwise implement differently.

It is deliberately a thin library: it contains no ROS node executable, owns no
Experiment lifecycle, and has no dependency on a simulator, robot, task,
evaluator, or concrete Agent.

## Runtime responsibilities

- Canonical QoS factories for latched control snapshots, velocity commands, and
  sensor data.
- Immediate component-status transitions plus periodic 1 Hz heartbeats.
- Steady-clock readiness and stale-heartbeat tracking, independent of `/clock`.
- Thread-safe reset idempotency with duplicate-result replay and conflicting
  request-ID rejection.
- Separate service discovery and call deadlines with structured failures.
- Explicit current-Episode selection and monotonically increasing sequence
  filtering.
- Validated conversion between core Pose3D/PointNav/lifecycle values and ROS
  messages.

## Contract details

Status, Episode state, PointNav task, and result snapshots use reliable,
transient-local, keep-last-one QoS. This lets late-joining consumers receive the
most recent authoritative snapshot. A `ComponentStatus.stamp` is committed only
on a transition; heartbeat republishes preserve it. Staleness is measured from
local receipt time with a steady clock because simulation time can be absent or
frozen during startup and failure handling.

`IdempotentResetGuard` requires the server adapter to construct a hashable
fingerprint from every behaviorally relevant request field. An equivalent
duplicate replays the first result without executing the backend again. Reusing
the same ID with different content is rejected. Completed records are bounded;
capacity should cover the maximum expected retry window.

`call_service_with_deadline` is intentionally blocking and requires the node's
executor to spin on another thread. It distinguishes service discovery timeout,
call completion timeout, and service failure. It never retries implicitly.

Episode IDs are opaque strings. `EpisodeSequenceGuard.activate()` must therefore
be called explicitly for each new Episode; the guard never guesses ordering from
an ID. It then accepts only matching messages whose sequence strictly increases.

## Model boundary

The conversion module is the only owner of ROS/core mapping. It converts the
complete initial 3D pose to `PoseStamped` with a normalized quaternion and the
PointNav 3D target position to `PointStamped`. PointNav does not gain a target
orientation through this adapter. Incoming quaternions and numeric values are
validated before core values are exposed.

Concrete components remain responsible for:

- deciding when they are genuinely READY;
- implementing the actual reset and constructing its request fingerprint;
- mapping structured protocol failures to component-specific responses;
- activating the Episode expected by their business lifecycle; and
- spinning an executor appropriate for their callback concurrency.
