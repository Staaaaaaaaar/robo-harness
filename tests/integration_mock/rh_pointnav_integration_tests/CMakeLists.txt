cmake_minimum_required(VERSION 3.8)
project(rh_pointnav_integration_tests)

find_package(ament_cmake REQUIRED)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)

  ament_add_pytest_test(test_pointnav_runtime
    test/test_pointnav_runtime.py
    ENV ROS_DOMAIN_ID=78
    TIMEOUT 25
  )
endif()

ament_package()
