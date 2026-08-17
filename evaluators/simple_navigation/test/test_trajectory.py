import pytest

from rh_core import Point3D
from rh_eval_simple_navigation import TrajectorySampler


def _point(x: float, y: float, z: float) -> Point3D:
    return Point3D("map", x, y, z)


def test_path_length_uses_ordered_3d_euclidean_segments() -> None:
    sampler = TrajectorySampler()

    assert sampler.observe(1.0, _point(0.0, 0.0, 0.0))
    assert sampler.observe(2.0, _point(3.0, 4.0, 0.0))
    assert sampler.observe(3.0, _point(3.0, 4.0, 12.0))

    assert sampler.path_length_m == pytest.approx(17.0)
    assert len(sampler.samples) == 3


def test_reset_excludes_teleport_jump_from_next_trajectory() -> None:
    sampler = TrajectorySampler()
    sampler.observe(1.0, _point(10.0, 0.0, 0.0))

    sampler.reset()
    sampler.observe(2.0, _point(100.0, 0.0, 0.0))
    sampler.observe(3.0, _point(101.0, 0.0, 0.0))

    assert sampler.path_length_m == pytest.approx(1.0)
    assert len(sampler.samples) == 2


def test_duplicate_and_out_of_order_samples_are_ignored() -> None:
    sampler = TrajectorySampler()
    sampler.observe(2.0, _point(0.0, 0.0, 0.0))

    assert not sampler.observe(2.0, _point(10.0, 0.0, 0.0))
    assert not sampler.observe(1.0, _point(10.0, 0.0, 0.0))
    assert sampler.path_length_m == 0.0
    assert sampler.final_position == _point(0.0, 0.0, 0.0)


def test_invalid_frame_and_time_are_rejected() -> None:
    sampler = TrajectorySampler()

    with pytest.raises(ValueError, match="frame"):
        sampler.observe(1.0, Point3D("odom", 0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="non-negative"):
        sampler.observe(-1.0, _point(0.0, 0.0, 0.0))
