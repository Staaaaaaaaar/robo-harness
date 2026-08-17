# Lifecycle state reported by an Environment or Agent component.
# Existing numeric values are part of the wire contract and must not change.
uint8 STARTING=0
uint8 RESETTING=1
uint8 READY=2
uint8 ERROR=3

# Time of the latest state transition, not the heartbeat publication time.
builtin_interfaces/Time stamp

# Stable identifier of the component instance within an experiment.
string component_id

uint8 state

# Zero means no error. Non-zero code catalogs are owned by each component.
uint32 error_code

# Short human-readable context; consumers must not parse this field.
string detail

# True when an operator must restart or redeploy the component before reuse.
bool restart_required
