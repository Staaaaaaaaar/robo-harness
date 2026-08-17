# Simple Navigation Evaluator

`rh_eval_simple_navigation` is the side-channel observer for the PointNav MVP.
It subscribes directly to the immutable task, authoritative Episode state,
the Agent's task state, `/robot/odom`, and `/clock`. It never publishes
`cmd_vel` or changes the world.

The evaluator transforms odometry positions into `map` through TF2, samples
them in strict timestamp order, excludes reset motion by clearing its trajectory
before each RUNNING segment, and computes:

- `success`
- `elapsed_time_s` using simulation time
- `path_length_m` using 3D Euclidean distance
- `final_distance_to_goal_m`
- `timeout`
- `termination_reason`

An Agent `SUCCEEDED` result is checked against the first ground-truth odometry
sample at or after that result. Only an in-radius final position produces a
success candidate, so merely passing through the goal does not end navigation.
Agent failure and timeout are also submitted as candidates; the orchestrator
remains the only authority that commits Episode termination.
Metrics stay in memory in PR 09. Durable artifacts remain the responsibility of
the later Recorder PR.

Use the composed runtime entrypoint:

```bash
ros2 run rh_bringup experiment --profile pointnav_simple --ros-args \
  -p config_path:=/workspace/roboharness/configs/experiments/mvp.yaml
```

The evaluator has no application entrypoint. `rh_bringup` selects it through
the evaluator factory boundary.
