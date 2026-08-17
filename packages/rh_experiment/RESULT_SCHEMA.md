# Result schema v1

The filesystem tree is the durable source of truth for a RoboHarness run. ROS
`EpisodeResult` messages are compact notifications that may point at the final
`metrics.json`; they are not a replacement for these artifacts.

```text
results/<encoded-experiment-id>/
├── config.yaml
├── metadata.json
├── summary.json
└── episodes/
    └── <encoded-episode-id>/
        ├── episode.yaml
        ├── events.jsonl
        ├── trajectory.csv
        └── metrics.json
```

Every YAML/JSON/JSONL document carries `schema_version: 1`. Raw identifiers are
preserved inside documents. Directory names use deterministic percent encoding
and bounded hashing, so opaque IDs cannot escape the configured results root.

## Commit markers

`ResultRecorder.start()` atomically writes `config.yaml`, `summary.json`, and
`metadata.json` with `complete: false`. `begin_episode()` immediately creates a
parseable Episode directory with incomplete `metrics.json`, an empty JSONL
event stream, and a trajectory CSV header.

Episode completion writes the final trajectory and events before atomically
replacing `metrics.json` with `complete: true`. Experiment completion writes the
final summary before atomically replacing `metadata.json` with `complete: true`.
Consequently, a reader can treat these two fields as the Episode and Experiment
commit markers. A process interruption never requires parsing a partially
written replacement file.

## Artifacts

- `config.yaml`: canonical validated `ExperimentConfig`, including all ordered
  Episode specifications.
- `metadata.json`: experiment identity, completeness, UTC start/finish times,
  git SHA, image digests, ROS distribution, and optional Isaac version.
- `episode.yaml`: experiment identity and the canonical Episode specification.
- `events.jsonl`: contiguous low-rate event records with identity, sequence,
  optional simulation time, detail, and an extensible JSON payload.
- `trajectory.csv`: strictly increasing simulation timestamps and finite 3D
  positions in one named frame.
- `metrics.json`: success, simulation elapsed time, path length, final goal
  distance, timeout, termination reason name/code, and trajectory sample count.
- `summary.json`: ordered Episode commit state and counts for every stable
  termination reason.

Numbers are strict JSON values; `NaN` and infinity are never emitted. Writers
refuse to overwrite an existing experiment directory. The independent
`validate_result_tree()` reader verifies layout, identity, schema version,
commit consistency, reason codes, event ordering, and trajectory contents.
