from types import SimpleNamespace
from wayfinder.app.controllers.map_controller import MapControllerMixin


def test_exit_marker_uses_known_native_destination_reachability():
    obj=object.__new__(MapControllerMixin)
    obj.snapshot=SimpleNamespace(
        entrance_details=[{"name":"Door","target_region":"Dragon Roost Cavern","unknown_destination":False,"reachable":True}],
        reachability_available=True,
    )
    marker=SimpleNamespace(location_name="Dragon Roost Cavern")
    assert obj._map_exit_marker_status(marker)=="reachable"


def test_exit_marker_does_not_spoil_unknown_randomized_destination():
    obj=object.__new__(MapControllerMixin)
    obj.snapshot=SimpleNamespace(
        entrance_details=[{"name":"Door","target_region":"Dragon Roost Cavern","unknown_destination":True,"reachable":True}],
        reachability_available=True,
    )
    marker=SimpleNamespace(location_name="Dragon Roost Cavern")
    assert obj._map_exit_marker_status(marker)=="unknown"
