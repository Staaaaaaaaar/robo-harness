# Contract tests

This domain contains black-box tests for public RoboHarness contracts. The
`rh_interfaces_contract_tests` package verifies generated C++ and Python ROS 2
types, stable field/constant definitions, serialization round trips, and the
interface package dependency boundary.

`rh_core_contract_tests` verifies that the ROS-independent domain enums remain
aligned with the wire constants, that the initial 3D pose and PointNav goal map
to their wire contracts without dimensional loss, and that core source and
manifest dependencies remain ROS-free.
