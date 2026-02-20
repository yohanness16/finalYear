"""CV engine density estimation tests."""

from app.services.cv_engine import estimate_density


def test_estimate_density_low():
    assert estimate_density(1000) == 0
    assert estimate_density(2999) == 0


def test_estimate_density_medium():
    assert estimate_density(3000) == 1
    assert estimate_density(5000) == 1
    assert estimate_density(6999) == 1


def test_estimate_density_high():
    assert estimate_density(7000) == 2
    assert estimate_density(10000) == 2
