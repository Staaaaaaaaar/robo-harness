cmake_minimum_required(VERSION 3.8)
project(rh_interfaces_contract_tests)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_gtest REQUIRED)
find_package(ament_cmake_pytest REQUIRED)
find_package(rh_interfaces REQUIRED)
find_package(rosidl_typesupport_cpp REQUIRED)

ament_add_gtest(test_cpp_typesupport test/test_cpp_typesupport.cpp)
ament_target_dependencies(test_cpp_typesupport
  rh_interfaces
  rosidl_typesupport_cpp
)

ament_add_pytest_test(test_python_contract test/test_python_contract.py
  TIMEOUT 30
)

ament_package()
