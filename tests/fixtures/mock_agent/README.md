# Mock Agent Fixture

`rh_mock_agent` is a deterministic CPU-only test double for the RoboHarness
Agent runtime contract. It is not a navigation implementation.

The fixture accepts an idempotent Agent reset, one immutable PointNav snapshot
for the active Episode, authoritative Episode state snapshots, and simulation
clock updates. It publishes a configurable sequence of planar `Twist` commands
only while all three gates are satisfied: the Episode was reset, its matching
task was accepted, and its latest accepted state is `RUNNING`.

The command script is configured by four equal-length ROS parameter arrays:
`script_durations_s`, `script_linear_x`, `script_linear_y`, and
`script_angular_z`. Script progress uses `/clock`, so wall-clock scheduling does
not alter the command sequence.

Fault parameters cover delayed/absent readiness, reset failure, heartbeat
suppression, an observable `ERROR`, and deliberate process failure. Script and
startup timing parameters are immutable after node construction.

This package must remain free of keyboard input, planners, learned policies,
goal-following logic, and platform-specific control adapters.
