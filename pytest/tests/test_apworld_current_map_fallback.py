from unittest.mock import Mock
from wayfinder.app.app import WayFinderApp
from wayfinder.connection.runtime_client import Snapshot


def test_dashboard_uses_apworld_current_map_raw_value_when_target_unresolved():
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game='Flipwitch Forbidden Sex Hex')
    app.snapshot.map_page_setting_key='flipwitchZone_0_3'; app.snapshot.raw_map_page_datastorage_value='Witchy Woods'
    app.map_last_game='Flipwitch Forbidden Sex Hex'; app.map_last_runtime_target=None
    assert app._dashboard_current_area() == 'Witchy Woods'


def test_map_area_label_uses_apworld_current_map_raw_value_when_target_unresolved():
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game='Flipwitch Forbidden Sex Hex')
    app.snapshot.map_page_setting_key='flipwitchZone_0_3'; app.snapshot.raw_map_page_datastorage_value='Witchy Woods'; app.snapshot.player_position_label=''
    app.map_last_runtime_target=None; app.map_current_area=Mock(); app.map_area_progress_detail=Mock(); app.map_area_progress_scale=Mock()
    app._current_map_status_counts=lambda: ({'reachable':0,'glitched':0,'out_of_logic':0,'checked':0,'ignored':0,'non_progression':0,'unknown':0},0)
    app._draw_current_area_progress=Mock(); app._refresh_current_area_progress()
    app.map_current_area.set.assert_called_once_with('Current area: Witchy Woods')


def test_runtime_target_directly_matches_raw_apworld_current_map_value():
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game='Game'); app.snapshot.raw_map_page_datastorage_value='Witchy Woods'; app.snapshot.map_page_index=-1; app.snapshot.player_position_map_index=-1
    app._ut_map_page_title=Mock(return_value=None)
    pack=Mock(); pack.has_python=False; pack.python_api_compatible=False; pack.maps=[]
    assert app._runtime_map_target(pack,['Witchy Woods','Spirit City']) == 'Witchy Woods'


def test_runtime_target_matches_apworld_area_to_map_image_stem_for_abbreviated_page():
    from wayfinder.maps.packs import MapDefinition
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game='Game'); app.snapshot.raw_map_page_datastorage_value='Witchy Woods'; app.snapshot.map_page_index=-1; app.snapshot.player_position_map_index=-1
    app._ut_map_page_title=Mock(return_value=None)
    pack=Mock(); pack.has_python=False; pack.python_api_compatible=False
    pack.maps=[MapDefinition(name='Ww', title='Ww', image='images/maps/WitchyWoods.png')]
    assert app._runtime_map_target(pack,['Ww']) == 'Ww'
