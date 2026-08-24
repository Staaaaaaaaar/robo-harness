# Isaac Sim backend

This directory contains the Isaac Sim 4.5 application boundary for the
RoboHarness `env` service. PR 13 intentionally provides only:

- the `rh.kit` application definition;
- the `rh.isaac` lifecycle extension;
- the native ROS 2 Bridge simulation-clock Action Graph; and
- headless and local-X11 launch modes.

The extension publishes `/roboharness/env/status` as `STARTING` while the Bridge
smoke is active and changes it to `ERROR` if initialization fails. It does not
publish `READY`: a complete READY claim requires the world, ANYmal C binding,
sensors, command gate, and reset contract planned for PR 14 and PR 16.

The Kit extension waits for app readiness, initializes Isaac Sim's
`SimulationContext` asynchronously, creates the clock graph in the simulation
pipeline, and starts the timeline. This follows the extension workflow where
Kit owns rendering/update timing and `SimulationContext` owns physics state.

No Isaac Lab dependency is installed. ANYmal C assets, policy integration,
sensor graphs, odometry, TF, and command handling are deliberately absent from
this skeleton.

## Directory ownership

```text
simulators/isaac/
├── apps/rh.kit                         # incremental Kit application config
├── bridge/topics.yaml                  # native Bridge contract manifest
├── extensions/rh.isaac/
│   ├── config/extension.toml           # Kit extension declaration
│   └── rh/isaac/
│       ├── extension.py                # lifecycle and status glue
│       └── clock_graph.py              # native OmniGraph construction
└── scripts/launch.sh                   # container headless/GUI launcher
```

Container builds, Compose services, consent values, and host GPU setup do not
belong here. They remain under `deployment/` and `docs/guides/`. The structure
follows the Isaac Sim App Template split between `.kit` applications and Kit
extensions, adapted to RoboHarness's domain-oriented monorepo.

The launcher starts the bundled `isaacsim.exp.base.kit` and merges `rh.kit` as
project configuration. The clock graph uses the native Bridge nodes
`OnPlaybackTick`, `ROS2Context`, `IsaacReadSimulationTime`, and
`ROS2PublishClock`; it does not implement a parallel ROS transport.

See the
[development environment and adjustment record](../../docs/guides/isaac-pr13-development-environment.md)
for the decisions confirmed while bringing up the container, Toolkit/CDI, Kit,
and ROS 2 Bridge.
