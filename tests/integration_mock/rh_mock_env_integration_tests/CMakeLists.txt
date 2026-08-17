cmake_minimum_required(VERSION 3.8)
project(rh_mock_env_integration_tests)

find_package(ament_cmake REQUIRED)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)

  ament_add_pytest_test(test_mock_env_black_box
    test/test_mock_env_black_box.py
    TIMEOUT 25
  )
endif()

ament_package()
