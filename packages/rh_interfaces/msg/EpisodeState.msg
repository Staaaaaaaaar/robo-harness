# Authoritative lifecycle state published by the Experiment orchestrator.
# Existing numeric values are part of the wire contract and must not change.
uint8 PREPARING=0
uint8 READY=1
uint8 RUNNING=2
uint8 TERMINATING=3
uint8 FINISHED=4

# A reason is final only when state is FINISHED. NONE is used before then.
uint8 NONE=0
uint8 SUCCESS=1
uint8 TIMEOUT=2
uint8 ABORTED=3
uint8 FAILURE=4
uint8 ENV_ERROR=5
uint8 AGENT_ERROR=6
uint8 INVALID_TASK=7

# Simulation time of this state transition.
builtin_interfaces/Time stamp

string experiment_id
string episode_id

# Strictly increases for every transition within an episode.
uint64 sequence

uint8 state
uint8 termination_reason

# Short human-readable context; consumers must not parse this field.
string detail
