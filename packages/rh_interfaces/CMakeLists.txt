cmake_minimum_required(VERSION 3.8)
project(rh_interfaces)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AgentTaskState.msg"
  "msg/ComponentStatus.msg"
  "msg/EpisodeResult.msg"
  "msg/EpisodeState.msg"
  "msg/PointNavTask.msg"
  "srv/AbortEpisode.srv"
  "srv/ResetAgent.srv"
  "srv/ResetEnv.srv"
  "srv/StartEpisode.srv"
  DEPENDENCIES
    builtin_interfaces
    geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)

if(BUILD_TESTING)
  find_package(ament_cmake_lint_cmake REQUIRED)
  find_package(ament_cmake_xmllint REQUIRED)

  ament_lint_cmake()
  ament_xmllint()
endif()

ament_package()
