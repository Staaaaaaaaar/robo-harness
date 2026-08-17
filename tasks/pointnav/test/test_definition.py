import math

import pytest

from rh_core import EpisodeSpec, Point3D, PointNavTaskSpec, Pose3D
from rh_pointnav import PointNavDefinition, PointNavValidationError


def _episode(
    *,
    goal: Point3D = Point3D("map", 4.0, 5.0, 1.0),
    radius: float = 0.5,
    timeout: float = 30.0,
    initial_frame: str = "map",
) -> EpisodeSpec:
    return EpisodeSpec(
        episode_id="episode-1",
        scenario="warehouse",
        initial_pose=Pose3D(initial_frame, 1.0, 2.0, 0.4, 0.1, -0.2, 0.3),
        task=PointNavTaskSpec(goal, radius, timeout),
        seed=42,
    )


def test_definition_preserves_3d_goal_without_orientation() -> None:
    definition = PointNavDefinition.from_episode("experiment-1", _episode())

    assert definition.goal == Point3D("map", 4.0, 5.0, 1.0)
    assert not hasattr(definition.goal, "yaw")
    assert definition.success_radius_m == 0.5
    assert definition.timeout_s == 30.0
    assert definition.seed == 42


@pytest.mark.parametrize(
    ("episode", "match"),
    [
        (_episode(goal=Point3D("odom", 1.0, 2.0, 3.0)), "goal frame"),
        (_episode(initial_frame="odom"), "initial pose frame"),
        (_episode(radius=0.0), "success_radius_m"),
        (_episode(radius=-1.0), "success_radius_m"),
        (_episode(timeout=0.0), "timeout_s"),
        (_episode(timeout=-1.0), "timeout_s"),
        (_episode(goal=Point3D("map", math.nan, 0.0, 0.0)), "finite"),
    ],
)
def test_invalid_pointnav_inputs_are_rejected_before_publication(
    episode: EpisodeSpec,
    match: str,
) -> None:
    with pytest.raises(PointNavValidationError, match=match):
        PointNavDefinition.from_episode("experiment-1", episode)


@pytest.mark.parametrize("experiment_id", ["", " "])
def test_experiment_identity_must_not_be_empty(experiment_id: str) -> None:
    with pytest.raises(PointNavValidationError, match="experiment_id"):
        PointNavDefinition.from_episode(experiment_id, _episode())


def test_episode_identity_matching_is_exact() -> None:
    definition = PointNavDefinition.from_episode("experiment-1", _episode())

    assert definition.matches_episode("experiment-1", "episode-1")
    assert not definition.matches_episode("experiment-1", "episode-2")
    assert not definition.matches_episode("experiment-2", "episode-1")


def test_goal_predicate_uses_3d_euclidean_distance_and_matching_frame() -> None:
    definition = PointNavDefinition.from_episode("experiment-1", _episode())

    assert definition.distance_to_goal(Point3D("map", 4.0, 5.0, 1.3)) == pytest.approx(
        0.3
    )
    assert definition.goal_reached(Point3D("map", 4.0, 5.0, 1.5))
    assert not definition.goal_reached(Point3D("map", 4.0, 5.0, 1.500001))
    with pytest.raises(PointNavValidationError, match="frames"):
        definition.distance_to_goal(Point3D("odom", 4.0, 5.0, 1.0))


def test_timeout_predicate_uses_non_negative_simulation_elapsed_time() -> None:
    definition = PointNavDefinition.from_episode("experiment-1", _episode())

    assert not definition.timed_out(29.999)
    assert definition.timed_out(30.0)
    with pytest.raises(PointNavValidationError, match="non-negative"):
        definition.timed_out(-0.1)
    with pytest.raises(PointNavValidationError, match="finite"):
        definition.timed_out(math.inf)
