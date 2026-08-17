# Evaluators

Evaluator implementations live under `evaluators/<evaluator>/`. They observe
task and telemetry data without forwarding or modifying robot control commands.

`simple_navigation/` contains the PointNav MVP observer. It computes metrics in
simulation time, confirms Agent completion against ground truth, and submits
termination candidates to the authoritative orchestrator without publishing
robot commands. Evaluators expose implementations only; `rh_bringup` owns
runtime composition.
