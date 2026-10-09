from clipatlas.domain.vehicle_names import canonical_vehicle_name


def test_vehicle_names_do_not_cross_normalize_models():
    assert canonical_vehicle_name("\u6cf0\u94bd700") == "\u6cf0\u94bd700"
    assert canonical_vehicle_name("\u5766\u514b700") == "\u5766\u514b700"
    assert canonical_vehicle_name("Tank 700") == "Tank 700"
    assert canonical_vehicle_name("\u6cf0\u94bd 700") == "\u6cf0\u94bd700"
