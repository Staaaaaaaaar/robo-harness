cmake_minimum_required(VERSION 3.8)
project(rh_simple_navigation_integration_tests)

find_package(ament_cmake REQUIRED)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)

  ament_add_pytest_test(test_simple_navigation_runtime
    test/test_simple_navigation_runtime.py
    ENV ROS_DOMAIN_ID=79
    TIMEOUT 30
  )
endif()

ament_package()
