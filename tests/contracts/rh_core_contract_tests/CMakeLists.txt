cmake_minimum_required(VERSION 3.8)
project(rh_core_contract_tests)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_pytest REQUIRED)

ament_add_pytest_test(test_core_interface_alignment test/test_core_interface_alignment.py
  TIMEOUT 30
)

ament_package()
