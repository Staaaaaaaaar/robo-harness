# Immutable PointNav task snapshot. PointNav specifies a 3D target position,
# not a desired target orientation. A future PoseNav task must use a distinct
# interface. The MVP requires the goal frame to be "map".
string experiment_id
string episode_id

geometry_msgs/PointStamped goal

# Goal is reached when the 3D Euclidean distance from the configured robot
# tracking point (MVP: base_link origin) is less than or equal to this value.
float64 success_radius_m

# Episode timeout measured in simulation seconds.
float64 timeout_s

# Reproducibility seed; interpretation is owned by the selected backend/task.
int64 seed
