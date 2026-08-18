cmake_minimum_required(VERSION 3.8)
project(rh_experiment_integration_tests)

find_package(ament_cmake REQUIRED)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)

  ament_add_pytest_test(test_single_episode_orchestrator
    test/test_single_episode_orchestrator.py
    ENV ROS_DOMAIN_ID=77
    TIMEOUT 25
  )

  ament_add_pytest_test(test_multi_episode_orchestrator
    test/test_multi_episode_orchestrator.py
    ENV ROS_DOMAIN_ID=80
    TIMEOUT 30
  )
endif()

ament_package()
