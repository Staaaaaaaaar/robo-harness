# Agent-owned execution state for the active Episode. This is an advisory
# navigation result, not the authoritative benchmark outcome. Before publishing
# SUCCEEDED, the Agent must stop producing non-zero commands and remain stopped.
uint8 IDLE=0
uint8 RUNNING=1
uint8 SUCCEEDED=2
uint8 FAILED=3

# Simulation time at which the Agent made this transition.
builtin_interfaces/Time stamp

string experiment_id
string episode_id

# Strictly increases for Agent transitions within one Episode.
uint64 sequence

uint8 state

# Human-readable context; consumers must not parse this field.
string detail
