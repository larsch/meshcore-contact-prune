"""Placeholder test — real tests need a MeshCore device."""

from meshcore_contact_prune import haversine_km


def test_haversine_same_point():
    assert haversine_km(55.0, 12.0, 55.0, 12.0) < 0.01


def test_haversine_known_distance():
    # Copenhagen → Berlin ≈ 350–360 km
    d = haversine_km(55.676, 12.568, 52.520, 13.405)
    assert 340 < d < 370


def test_haversine_zero_location():
    assert haversine_km(0.0, 0.0, 55.0, 12.0) == float("inf")
    assert haversine_km(55.0, 12.0, 0.0, 0.0) == float("inf")
