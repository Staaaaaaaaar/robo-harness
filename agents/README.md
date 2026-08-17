# Agents

Agent implementations live under `agents/<agent>/`. They consume public ROS
observations and platform contracts and publish robot commands; they do not own
the simulator, experiment scheduling, evaluation, or persistence.

The keyboard agent is introduced by PR 15.
