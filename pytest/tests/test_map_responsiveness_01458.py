"""Behavioral regressions for deferred map following and responsive rendering."""
from types import SimpleNamespace
from unittest.mock import Mock
import tkinter as tk
import pytest
from PIL import Image
from wayfinder.app.app import WayFinderApp, Snapshot


def test_reopening_reconciles_player_target_before_rendering():
    """Handle test reopening reconciles player target before rendering."""
    app=object.__new__(WayFinderApp)
    app._closing=False;app.current_page='Map';app._map_render_deferred=True
    pack=SimpleNamespace(has_python=False, variants={}, display_name='Test', maps=[1,2],markers=[])
    app.snapshot=Snapshot(game='Test')
    app.active_map_pack=pack;app.map_last_game='Test';app.map_last_runtime_target='Old'
    app.map_canvas=Mock();app.map_selector_var=Mock();app.map_selector_var.get.return_value='Old'
    app.map_status=Mock();app._preferred_map_pack=lambda *a:(pack,0)
    app._ut_ordered_map_titles=lambda *a:['Old','New']
    app._runtime_map_target=lambda *a:'New'
    app._remember_current_map=Mock();app._request_map_render=Mock()
    app._refresh_map_markers=Mock();app._refresh_current_area_progress=Mock();app._refresh_dashboard_overview=Mock()
    app._resume_map_page()
    app.map_selector_var.set.assert_called_once_with('New')
    assert app.map_last_runtime_target=='New'
    assert not app._map_render_deferred
    app.map_selector_var.set.reset_mock()
    app.map_selector_var.get.return_value='Manual'
    app._resume_map_page()
    # Same runtime area: preserve the map the user chose to browse.
    app.map_selector_var.set.assert_not_called()


def test_leaving_tab_before_idle_does_not_render():
    """Handle test leaving tab before idle does not render."""
    app=object.__new__(WayFinderApp)
    app._closing=False;app.current_page='Checks'
    app._refresh_map_from_snapshot=Mock()
    app._resume_map_page()
    app._refresh_map_from_snapshot.assert_not_called()


def test_zoom_reuses_canvas_items_but_map_change_rebuilds():
    """Handle test zoom reuses canvas items but map change rebuilds."""
    app=object.__new__(WayFinderApp)
    app.map_canvas=Mock();app.map_zoom=Mock();app.map_zoom.get.return_value=50
    app._map_marker_layout_key=None;app._map_marker_items={};app._map_marker_visual_state={}
    app.font_size=Mock();app.font_size.get.return_value=12
    app._map_display_name=lambda s:s;app._palette=lambda:{'success':'green'}
    marker=SimpleNamespace(location_name='Check',member_names=('Check',))
    pack=SimpleNamespace(markers_by_map={'a':[marker],'b':[marker]})
    app._ensure_map_marker_items(pack,SimpleNamespace(name='a'),.5)
    count=app.map_canvas.create_oval.call_count
    app.map_zoom.get.return_value=75
    app._ensure_map_marker_items(pack,SimpleNamespace(name='a'),.75)
    assert app.map_canvas.create_oval.call_count==count
    app._ensure_map_marker_items(pack,SimpleNamespace(name='b'),.75)
    assert app.map_canvas.create_oval.call_count>count


def test_spatial_collision_handles_negative_coordinates_and_distant_markers():
    """Handle test spatial collision handles negative coordinates and distant markers."""
    app=object.__new__(WayFinderApp)
    points=[(-1,-1),(1,1),(100,100),(200,200)]
    markers=[SimpleNamespace(x=x,y=y) for x,y in points]
    positions=app._map_marker_display_positions(markers,1,3)
    assert positions[0]!=points[0] and positions[1]!=points[1]
    assert positions[2]==points[2] and positions[3]==points[3]


def test_strip_upload_yields_and_obsolete_upload_never_applies():
    """Handle test strip upload yields and obsolete upload never applies."""
    try:root=tk.Tk()
    except tk.TclError:pytest.skip('Tk display unavailable')
    root.withdraw()
    app=object.__new__(WayFinderApp)
    app.root=root;app._closing=False;app.map_render_generation=1;app.map_rendering_key='first'
    app.map_photo_cache={};app._apply_map_photo=Mock();app._map_render_failed=Mock()
    image=Image.new('RGBA',(64,800),'red')
    try:
        app._upload_map_photo(1,'first',image,0,0,False)
        app._apply_map_photo.assert_not_called()
        app.map_render_generation=2;app.map_rendering_key='second'
        app._upload_map_photo(2,'second',image,0,0,False)
        root.after(100,root.quit);root.mainloop()
        app._apply_map_photo.assert_called_once()
        args=app._apply_map_photo.call_args.args
        assert args[0]=='second'
        y,tile=args[1].tiles[-1]
        assert y+tile.height()==800
        assert root.tk.call(str(tile),'get',0,tile.height()-1)==(255,0,0)
        app._map_render_failed.assert_not_called()
    finally:root.destroy()


def test_tiled_background_places_every_strip_at_its_original_offset():
    """Handle test tiled background places every strip at its original offset."""
    from wayfinder.maps.assets import TiledMapPhoto, draw_map_photo
    photo=TiledMapPhoto(64,800)
    photo.tiles=[(0,object()),(256,object()),(512,object()),(768,object())]
    for canvas in (Mock(),Mock()):  # main map and popout use identical placement
        draw_map_photo(canvas,photo)
        assert [call.args for call in canvas.create_image.call_args_list]==[(0,y) for y,_ in photo.tiles]
        assert all(call.kwargs['tags']==('map_image',) for call in canvas.create_image.call_args_list)
