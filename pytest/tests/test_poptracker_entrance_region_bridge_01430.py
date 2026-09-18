"""Provide test poptracker entrance region bridge 01430 support."""
from types import SimpleNamespace


def test_region_bridge_resolves_mismatched_poptracker_entrance_label():
    # Import the method without constructing the full Tk application.
    """Handle test region bridge resolves mismatched poptracker entrance label."""
    from wayfinder.app.app import WayFinderApp

    completion = SimpleNamespace(name='Rift Completion', region='Time Rift Interior', status='out_of_logic', ignored=False)
    snapshot = SimpleNamespace(
        locations=[completion],
        entrance_details=[{
            'name':'Internal APWorld Rift Entrance',
            'source_region':'Mafia Town',
            'target_region':'Time Rift Interior',
            'reachable':True,
            'status':'reachable',
        }],
        current_reachable_regions=['Mafia Town','Time Rift Interior'],
        reachability_available=True,
    )
    marker = SimpleNamespace(
        location_name='Time Rift - Sewers',
        member_names=('Can Enter','Can Complete'),
        section_ids=((), (12345,)),
    )
    app=object.__new__(WayFinderApp)
    app.snapshot=snapshot
    app._map_marker_member_location=lambda marker,index,state=None: completion if index==1 else None
    assert app._map_entrance_marker_status(marker)=='reachable'


def test_region_bridge_reports_blocked_when_destination_region_is_not_reachable():
    """Handle test region bridge reports blocked when destination region is not reachable."""
    from wayfinder.app.app import WayFinderApp

    completion = SimpleNamespace(name='Rift Completion', region='Time Rift Interior', status='out_of_logic', ignored=False)
    snapshot = SimpleNamespace(
        locations=[completion],
        entrance_details=[{
            'name':'Internal APWorld Rift Entrance',
            'source_region':'Mafia Town',
            'target_region':'Time Rift Interior',
            'reachable':False,
            'status':'blocked',
        }],
        current_reachable_regions=['Mafia Town'],
        reachability_available=True,
    )
    marker = SimpleNamespace(
        location_name='Time Rift - Sewers',
        member_names=('Can Enter','Can Complete'),
        section_ids=((), (12345,)),
    )
    app=object.__new__(WayFinderApp)
    app.snapshot=snapshot
    app._map_marker_member_location=lambda marker,index,state=None: completion if index==1 else None
    assert app._map_entrance_marker_status(marker)=='out_of_logic'
