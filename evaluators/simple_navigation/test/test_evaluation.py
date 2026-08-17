import pytest

from rh_core import EpisodeSpec, Point3D, PointNavTaskSpec, Pose3D, TerminationReason
from rh_eval_simple_navigation import SimpleNavigationEvaluation
from rh_pointnav import PointNavDefinition


def _definition(
    *,
    radius: float = 0.5,
    timeout: float = 10.0,
) -> PointNavDefinition:
    episode = EpisodeSpec(
        episode_id="episode-1",
        scenario="warehouse",
        initial_pose=Pose3D("map", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        task=PointNavTaskSpec(Point3D("map", 3.0, 4.0, 12.0), radius, timeout),
        seed=42,
    )
    return PointNavDefinition.from_episode("experiment-1", episode)


def test_fixed_trajectory_produces_stable_success_metrics() -> None:
    evaluation = SimpleNavigationEvaluation(_definition())
    evaluation.start(100.0)

    assert evaluation.observe_position(101.0, Point3D("map", 0.0, 0.0, 0.0)) is None
    assert evaluation.observe_position(102.0, Point3D("map", 3.0, 4.0, 0.0)) is None
    assert evaluation.report_agent_succeeded(103.0) is None
    candidate = evaluation.observe_position(
        103.0,
        Point3D("map", 3.0, 4.0, 11.5),
    )

    assert candidate is not None
    assert candidate.reason is TerminationReason.SUCCESS
    assert evaluation.metrics.success
    assert evaluation.metrics.elapsed_time_s == pytest.approx(3.0)
    assert evaluation.metrics.path_length_m == pytest.approx(16.5)
    assert evaluation.metrics.final_distance_to_goal_m == pytest.approx(0.5)
    assert evaluation.metrics.sample_count == 3


def test_success_has_priority_over_timeout_at_same_pose_update() -> None:
    evaluation = SimpleNavigationEvaluation(_definition(timeout=3.0))
    evaluation.start(10.0)
    assert evaluation.report_agent_succeeded(13.0) is None

    candidate = evaluation.observe_position(
        13.0,
        Point3D("map", 3.0, 4.0, 12.0),
    )

    assert candidate is not None
    assert candidate.reason is TerminationReason.SUCCESS


def test_crossing_goal_without_agent_completion_does_not_end_episode() -> None:
    evaluation = SimpleNavigationEvaluation(_definition())
    evaluation.start(10.0)

    assert (
        evaluation.observe_position(11.0, Point3D("map", 3.0, 4.0, 12.0))
        is None
    )
    assert evaluation.running
    assert not evaluation.metrics.success


def test_agent_completion_outside_goal_is_a_failed_navigation() -> None:
    evaluation = SimpleNavigationEvaluation(_definition())
    evaluation.start(10.0)
    evaluation.observe_position(11.0, Point3D("map", 0.0, 0.0, 0.0))

    candidate = evaluation.report_agent_succeeded(11.0)

    assert candidate is not None
    assert candidate.reason is TerminationReason.FAILURE


def test_timeout_uses_simulation_time_without_odometry() -> None:
    evaluation = SimpleNavigationEvaluation(_definition(timeout=5.0))
    evaluation.start(20.0)

    assert evaluation.advance_clock(24.999) is None
    candidate = evaluation.advance_clock(25.0)

    assert candidate is not None
    assert candidate.reason is TerminationReason.TIMEOUT
    assert evaluation.metrics.timeout
    assert evaluation.metrics.elapsed_time_s == pytest.approx(5.0)
    assert evaluation.metrics.final_distance_to_goal_m is None


def test_out_of_order_clock_does_not_change_elapsed_time() -> None:
    evaluation = SimpleNavigationEvaluation(_definition())
    evaluation.start(50.0)
    evaluation.advance_clock(52.0)

    assert evaluation.advance_clock(51.0) is None
    assert evaluation.metrics.elapsed_time_s == pytest.approx(2.0)


def test_prepare_clears_previous_episode_segment() -> None:
    evaluation = SimpleNavigationEvaluation(_definition())
    evaluation.start(1.0)
    evaluation.observe_position(2.0, Point3D("map", 0.0, 0.0, 0.0))

    evaluation.prepare()
    evaluation.start(10.0)
    evaluation.observe_position(11.0, Point3D("map", 100.0, 0.0, 0.0))

    assert evaluation.metrics.path_length_m == 0.0
    assert evaluation.metrics.sample_count == 1
