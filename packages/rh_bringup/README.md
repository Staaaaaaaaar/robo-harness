# RoboHarness Bringup

`rh_bringup` is the only composition root inside the Experiment container. It
selects an explicit, reviewed Task/Evaluator assembly and starts the generic
orchestrator. It does not import or instantiate concrete Env or Agent nodes;
those remain separate ROS 2 processes in their own containers.

The initial reference profile is `pointnav_simple`:

```text
rh_experiment orchestrator
  + rh_pointnav task publisher
  + rh_eval_simple_navigation observer
```

Run it with:

```bash
ros2 run rh_bringup experiment --profile pointnav_simple --ros-args \
  -p config_path:=/workspace/roboharness/configs/experiments/mvp.yaml \
  -p experiment_id:=anymal-c-keyboard-run-001 \
  -p results_root:=/workspace/roboharness/results
```

The orchestrator executes every configured Episode serially. Choose a new
`experiment_id` for each recorded run because result directories are immutable
and are never overwritten.

New supported combinations are added to the small `ASSEMBLIES` registry. Task
and Evaluator packages expose implementations only and do not own application
entrypoints or lifecycle coordination.
