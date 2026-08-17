# Experiment Orchestrator

`rh_experiment` owns the RoboHarness control plane and is the sole publisher of
the authoritative `/roboharness/episode/state` snapshot.

The PR 07 implementation intentionally supports exactly one statically validated
Episode. It waits for fresh Env and Agent readiness, resets Env before Agent,
publishes `READY`, accepts manual start/abort requests, commits one termination
reason, performs a bounded reliable-state safe-stop handshake, and publishes
`FINISHED`. Automatic mode invokes the same internal start transition used by
the service.

The PR 07 handshake confirms reliable DDS/RMW delivery of the authoritative
`TERMINATING` snapshot to the matched component subscriptions. The current wire
contract has no component-level semantic acknowledgement, so the implementation
does not claim stronger confirmation than the available interface provides.

All lifecycle mutations run on one control thread. ROS executor callbacks only
update thread-safe status trackers or submit control events, so reset responses,
operator commands, and component failures cannot concurrently mutate state.

Required runtime parameter:

- `config_path`: validated Experiment YAML. PR 07 rejects configs containing
  more than one Episode.

Optional identity and deadline parameters are `experiment_id`,
`env_component_id`, `agent_component_id`, `startup_timeout_s`,
`status_stale_timeout_s`, `reset_timeout_s`, `safe_stop_timeout_s`, and
`control_request_timeout_s`. `simulation_clock_stale_timeout_s` is the
steady-time watchdog used only after an Episode enters `RUNNING`. Lifecycle
deadlines use steady time and do not depend on `/clock`.

The versioned [`Result Schema`](RESULT_SCHEMA.md) and ROS-independent
`ResultRecorder` provide atomic metadata, spec, event, trajectory, metric, and
summary artifacts. Recording begins with durable `complete=false` commit
markers, so interrupted runs remain independently parseable. PR 11 owns the
full lifecycle wiring and multi-Episode loop.

Concrete Task packages integrate through the small in-process
`EpisodeTaskPublisher` factory boundary. The generic lifecycle package does not
statically depend on PointNav or any future Task implementation.

Evaluators use an equivalent in-process factory boundary and may only submit
termination candidates through the orchestrator's serialized commit path. A
wall-clock watchdog classifies a stalled simulation clock as an Env failure;
Episode timeout semantics themselves remain based on simulation time.

`rh_experiment` is a reusable lifecycle engine, not an application entrypoint.
The `rh_bringup` composition root selects concrete Task/Evaluator factories and
starts this engine inside the Experiment container.
