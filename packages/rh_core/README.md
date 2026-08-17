# `rh_core`

`rh_core` is the ROS-independent domain layer of RoboHarness. It defines what
an Experiment means, which static configuration is valid, which lifecycle
transitions are legal, and how competing termination candidates are resolved.
It does not communicate with ROS or execute an Experiment.

## Responsibilities

- Immutable typed models for versioned Experiment, Episode, and PointNav input.
- Strict YAML decoding with unknown-field and duplicate-key rejection.
- Static validation that does not require a loaded simulator world.
- Pure Experiment and Episode lifecycle transition guards.
- Deterministic Episode termination priority.
- Structured errors containing a machine-readable code, field path, and
  human-readable message.

The package must not import `rclpy`, `rh_interfaces`, Isaac Sim, or any concrete
Simulator, Agent, Task, or Evaluator implementation. ROS message conversion
belongs to the future `rh_ros` package.

## Configuration schema version 1

The canonical example is
[`configs/experiments/mvp.yaml`](../../configs/experiments/mvp.yaml). A document
contains an Experiment name, execution mode, and a non-empty ordered list of
Episode specifications. Each MVP Episode references a scenario and contains an
immutable PointNav task plus a signed 64-bit reproducibility seed.

The loader validates:

- exact known fields and `schema_version: 1`;
- non-empty identifiers, scenario references, and Experiment names;
- unique Episode IDs;
- `manual` or `automatic` execution mode;
- PointNav as the only MVP task type;
- finite initial-pose position/orientation, goal, radius, and timeout values;
- positive radius and timeout;
- matching `map` initial-pose/goal frames; and
- an integer seed in the ROS `int64` range.

The Episode initial state is a full 3D robot pose: position is expressed in
metres and roll, pitch, and yaw in radians. RPY means fixed-axis rotations about
X, Y, and Z, with the equivalent rotation matrix
`Rz(yaw) * Ry(pitch) * Rx(roll)`. A source that only provides planar data must
explicitly adapt the absent `z`, roll, and pitch dimensions, normally to zero.
The ROS adapter converts this representation to a normalized `PoseStamped`
quaternion.

PointNav contains only a 3D goal position. It has no desired target orientation,
and success uses the 3D Euclidean distance from the configured robot tracking
point (MVP: the `base_link` origin) to the goal. PoseNav, if later required, will
be a separate task model and interface rather than an extension hidden inside
these PointNav fields.

Checks that require a loaded world, such as collision-free or reachable poses,
remain an Environment/Task concern during Episode `PREPARING`.

```python
from rh_core import ConfigError, load_experiment_config

try:
    config = load_experiment_config("configs/experiments/mvp.yaml")
except ConfigError as error:
    for issue in error.issues:
        print(issue.as_dict())
```

## Lifecycle rules

Experiment progression is:

```text
CREATED -> STARTING -> RUNNING -> FINALIZING -> FINISHED
                    \---------- errors ----------> FAILED
```

Episode progression is:

```text
PREPARING -> READY -> RUNNING -> TERMINATING -> FINISHED
     |          |         |
     +----------+---------+---- early termination
```

Entering `TERMINATING` requires a non-`NONE` reason. The reason is committed
once, retained through `FINISHED`, and cannot be replaced. Every accepted
Episode transition returns a new immutable snapshot with `sequence + 1`.

Termination candidates use this priority:

```text
ENV_ERROR > AGENT_ERROR > FAILURE > INVALID_TASK
          > ABORTED > SUCCESS > TIMEOUT
```

This refines the architectural rule “runtime safety error, user abort, success,
timeout” with deterministic ordering inside the failure tier. The Environment
wins ties because it is the final motion-safety boundary.
