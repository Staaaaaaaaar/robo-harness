# Compact completion event. Detailed results remain in the referenced artifact.
string experiment_id
string episode_id

# Uses the termination reason constants defined by EpisodeState.
uint8 termination_reason

# Convenience summary; true exactly when termination_reason is SUCCESS.
bool success

# Metrics are measured in simulation time and the map frame.
float64 elapsed_time_s
float64 path_length_m
float64 final_distance_to_goal_m

# Opaque URI for the durable episode result document.
string result_uri
