"""In-process boundary between orchestration and a concrete Task module."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rclpy.node import Node

from rh_core import EpisodeSpec


class EpisodeTaskPublisher(Protocol):
    """Publish the already validated immutable task for the active Episode."""

    def publish(self) -> None: ...

    def close(self) -> None: ...


EpisodeTaskPublisherFactory = Callable[
    [Node, str, EpisodeSpec],
    EpisodeTaskPublisher,
]
