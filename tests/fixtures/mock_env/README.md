# Mock Environment fixture

`rh_mock_env` is a deterministic, CPU-only black-box fixture for the
RoboHarness Environment ROS contract. It exists to make protocol and
orchestration tests fast and reproducible. It is not a simulator product and
must not be used to claim physics, sensor, robot, Gazebo, or Isaac Sim
compatibility.

The fixture provides:

- `/roboharness/env/status` readiness and heartbeat snapshots;
- idempotent `/roboharness/env/reset_episode` with complete 3D initial pose;
- `/clock`, `/robot/odom`, `map -> odom`, and `odom -> base_link`;
- `/robot/cmd_vel` integration with a simulation-time watchdog;
- `/roboharness/episode/state` filtering and a strict non-RUNNING zero gate;
- parameter-driven reset failure, clock freeze, readiness delay, and stale
  heartbeat injection.

Motion is intentionally simple: fixed-step planar body velocity is integrated
without acceleration, collision, gravity, contact, noise, or sensor models.
Reset height, roll, and pitch are preserved while motion changes x, y, and yaw.
The global simulation clock remains monotonic across Episode resets.

## Fault parameters

| Parameter | Default | Effect |
|---|---:|---|
| `ready_delay_s` | `0.0` | Delays the READY transition using steady time |
| `never_ready` | `false` | Keeps the component in STARTING |
| `reset_failure` | `false` | Returns a reset failure and enters ERROR |
| `freeze_clock` | `false` | Stops simulation time and motion advancement |
| `suppress_status_heartbeat` | `false` | Suppresses heartbeat publication |
| `command_timeout_s` | `0.5` | Zeros stale commands using simulation time |
| `update_rate_hz` | `20.0` | Fixed simulation update frequency |

Boolean runtime fault parameters may be changed through the standard ROS
parameter API. Startup and model-shape parameters are configured at node
construction and are not dynamically reconfigured.

```bash
ros2 run rh_mock_env mock_env --ros-args -p reset_failure:=true
```
