from builtin_interfaces.msg import Time

from rh_core import EpisodeSpec, Point3D, PointNavTaskSpec, Pose3D
from rh_pointnav.publisher import PointNavTaskPublisher


class _Clock:
    class _Now:
        @staticmethod
        def to_msg() -> Time:
            return Time(sec=7)

    @staticmethod
    def now() -> _Now:
        return _Clock._Now()


class _Publisher:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def publish(self, message: object) -> None:
        self.messages.append(message)


class _Node:
    def __init__(self) -> None:
        self.publisher = _Publisher()

    def create_publisher(self, *args: object) -> _Publisher:
        return self.publisher

    @staticmethod
    def get_clock() -> _Clock:
        return _Clock()


def _episode() -> EpisodeSpec:
    return EpisodeSpec(
        episode_id="episode-1",
        scenario="warehouse",
        initial_pose=Pose3D("map", 1.0, 2.0, 0.4, 0.0, 0.0, 0.3),
        task=PointNavTaskSpec(Point3D("map", 4.0, 5.0, 1.0), 0.5, 30.0),
        seed=42,
    )


def test_republication_preserves_one_immutable_wire_snapshot() -> None:
    node = _Node()
    publisher = PointNavTaskPublisher(node, "experiment-1", _episode())  # type: ignore[arg-type]

    publisher.publish()
    exposed = publisher.message
    exposed.goal.point.x = 999.0
    publisher.publish()

    assert publisher.publish_count == 2
    assert len(node.publisher.messages) == 2
    assert node.publisher.messages[0] is node.publisher.messages[1]
    assert node.publisher.messages[1].goal.point.x == 4.0
