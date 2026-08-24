# Simulators

Simulator backends live under `simulators/<simulator>/`. A backend owns its
world, physics, native ROS bridge, and backend-local robot bindings under
`robots/<robot>/`.

The selected GPU baseline is Isaac Sim 4.5.0 running alongside Ubuntu 22.04 and
ROS 2 Humble. ANYmal C is the first reference quadruped; its simulator-only
official locomotion-policy binding belongs to the Isaac backend. The MVP runs
the policy bundled with Isaac Sim and does not install Isaac Lab. Training or
exporting a policy is outside the current runtime scope.

Isaac Sim and ANYmal C implementation files are intentionally out of scope for PR 01.
