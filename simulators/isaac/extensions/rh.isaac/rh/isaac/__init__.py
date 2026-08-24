"""RoboHarness Isaac backend extension."""

from __future__ import annotations

import os
import sys

_ROS_PYTHON_PATH = os.environ.get(
    "RH_ROS_PYTHON_PATH",
    "/opt/roboharness/local/lib/python3.10/dist-packages",
)
if _ROS_PYTHON_PATH not in sys.path:
    sys.path.insert(0, _ROS_PYTHON_PATH)

from .extension import Extension  # noqa: E402 - overlay must precede this import

__all__ = ["Extension"]
