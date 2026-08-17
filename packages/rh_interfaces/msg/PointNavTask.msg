# Immutable PointNav task snapshot. start and goal must use the same frame.
# RoboHarness MVP requires that frame to be "map".
string experiment_id
string episode_id

geometry_msgs/PoseStamped start
geometry_msgs/PoseStamped goal

# Goal is reached when planar distance is less than or equal to this value.
float64 success_radius_m

# Episode timeout measured in simulation seconds.
float64 timeout_s

# Reproducibility seed; interpretation is owned by the selected backend/task.
int64 seed
