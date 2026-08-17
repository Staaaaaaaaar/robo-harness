#include <gtest/gtest.h>

#include "rh_interfaces/msg/component_status.hpp"
#include "rh_interfaces/msg/episode_result.hpp"
#include "rh_interfaces/msg/episode_state.hpp"
#include "rh_interfaces/msg/point_nav_task.hpp"
#include "rh_interfaces/srv/abort_episode.hpp"
#include "rh_interfaces/srv/reset_agent.hpp"
#include "rh_interfaces/srv/reset_env.hpp"
#include "rh_interfaces/srv/start_episode.hpp"
#include "rosidl_typesupport_cpp/message_type_support.hpp"
#include "rosidl_typesupport_cpp/service_type_support.hpp"

TEST(RhInterfacesContract, StableNumericConstants)
{
  using ComponentStatus = rh_interfaces::msg::ComponentStatus;
  EXPECT_EQ(ComponentStatus::STARTING, 0u);
  EXPECT_EQ(ComponentStatus::RESETTING, 1u);
  EXPECT_EQ(ComponentStatus::READY, 2u);
  EXPECT_EQ(ComponentStatus::ERROR, 3u);

  using EpisodeState = rh_interfaces::msg::EpisodeState;
  EXPECT_EQ(EpisodeState::PREPARING, 0u);
  EXPECT_EQ(EpisodeState::READY, 1u);
  EXPECT_EQ(EpisodeState::RUNNING, 2u);
  EXPECT_EQ(EpisodeState::TERMINATING, 3u);
  EXPECT_EQ(EpisodeState::FINISHED, 4u);

  EXPECT_EQ(EpisodeState::NONE, 0u);
  EXPECT_EQ(EpisodeState::SUCCESS, 1u);
  EXPECT_EQ(EpisodeState::TIMEOUT, 2u);
  EXPECT_EQ(EpisodeState::ABORTED, 3u);
  EXPECT_EQ(EpisodeState::FAILURE, 4u);
  EXPECT_EQ(EpisodeState::ENV_ERROR, 5u);
  EXPECT_EQ(EpisodeState::AGENT_ERROR, 6u);
  EXPECT_EQ(EpisodeState::INVALID_TASK, 7u);
}

TEST(RhInterfacesContract, CppTypesupportIsLinked)
{
  EXPECT_NE(
    rosidl_typesupport_cpp::get_message_type_support_handle<
      rh_interfaces::msg::ComponentStatus>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_message_type_support_handle<
      rh_interfaces::msg::EpisodeResult>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_message_type_support_handle<
      rh_interfaces::msg::EpisodeState>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_message_type_support_handle<
      rh_interfaces::msg::PointNavTask>(),
    nullptr);

  EXPECT_NE(
    rosidl_typesupport_cpp::get_service_type_support_handle<
      rh_interfaces::srv::AbortEpisode>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_service_type_support_handle<
      rh_interfaces::srv::ResetAgent>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_service_type_support_handle<
      rh_interfaces::srv::ResetEnv>(),
    nullptr);
  EXPECT_NE(
    rosidl_typesupport_cpp::get_service_type_support_handle<
      rh_interfaces::srv::StartEpisode>(),
    nullptr);
}

TEST(RhInterfacesContract, GeneratedCppTypesAreUsable)
{
  rh_interfaces::msg::ComponentStatus status;
  status.component_id = "env";
  status.state = status.READY;
  EXPECT_EQ(status.component_id, "env");

  rh_interfaces::msg::EpisodeState state;
  state.experiment_id = "experiment-1";
  state.episode_id = "episode-1";
  state.sequence = 4;
  state.state = state.FINISHED;
  state.termination_reason = state.SUCCESS;
  EXPECT_EQ(state.sequence, 4u);

  rh_interfaces::msg::PointNavTask task;
  task.start.header.frame_id = "map";
  task.goal.header.frame_id = "map";
  task.success_radius_m = 0.5;
  EXPECT_DOUBLE_EQ(task.success_radius_m, 0.5);

  rh_interfaces::srv::ResetEnv::Request reset_request;
  reset_request.request_id = "request-1";
  reset_request.start.header.frame_id = "map";
  EXPECT_EQ(reset_request.start.header.frame_id, "map");

  rh_interfaces::srv::ResetAgent::Response reset_response;
  reset_response.success = true;
  reset_response.error_code = 0;
  EXPECT_TRUE(reset_response.success);

  rh_interfaces::srv::StartEpisode::Response start_response;
  start_response.accepted = true;
  EXPECT_TRUE(start_response.accepted);

  rh_interfaces::srv::AbortEpisode::Request abort_request;
  abort_request.reason = "operator request";
  EXPECT_EQ(abort_request.reason, "operator request");
}
