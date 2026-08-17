# PointNav Task

`rh_pointnav` owns the first concrete RoboHarness Task. A PointNav goal is a
finite 3D position in the `map` frame; it never contains desired yaw or any
other target orientation. The complete initial pose remains an Environment
reset condition.

The module validates and freezes one task definition before Experiment startup,
publishes it directly to Env, Agent, and Evaluator with reliable transient-local
QoS after both resets succeed, and exposes pure 3D goal-distance, success-radius,
and simulation-time timeout predicates for later Evaluators.

Use the composed runtime entrypoint:

```bash
ros2 run rh_pointnav orchestrator --ros-args \
  -p config_path:=/workspace/roboharness/configs/experiments/mvp.yaml
```

The generic `rh_experiment` lifecycle package does not import this package.
`rh_pointnav` supplies the concrete publisher through its in-process task
factory boundary.
