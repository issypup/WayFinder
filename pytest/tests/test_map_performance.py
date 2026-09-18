"""Provide test map performance support."""
import json
import threading
import queue
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from wayfinder.maps import packs
from wayfinder.maps.assets import remember_image, cached_image, image_hash, asset_key, open_pack_image, render_result
from wayfinder.app.app import WayFinderApp


def make_pack(root, size=(24, 16)):
    """Return make pack."""
    (root/'maps').mkdir(parents=True)
    (root/'locations').mkdir()
    (root/'maps/maps.json').write_text(json.dumps([{'name':'test','img':'map.png'}]))
    (root/'locations/checks.json').write_text(json.dumps([{'name':'Check','map_locations':[{'map':'test','x':1,'y':2}]}]))
    Image.new('RGB',size,'red').save(root/'map.png')
    return packs._parse_pack(root)


def test_parsed_cache_reuses_parse_and_isolates_mutations(tmp_path):
    """Handle test parsed cache reuses parse and isolates mutations."""
    first=make_pack(tmp_path)
    first.maps[0].title='changed by caller'
    with patch.object(packs,'_parse_pack_uncached',side_effect=AssertionError('reparsed')):
        second=packs._parse_pack(tmp_path)
    assert second.maps[0].title=='Test'
    assert second.markers is not first.markers


def test_parsed_cache_invalidates_added_changed_deleted_metadata(tmp_path):
    """Handle test parsed cache invalidates added changed deleted metadata."""
    make_pack(tmp_path)
    path=tmp_path/'maps/maps.json'
    path.write_text('[{"name":"new","img":"map.png"}]')
    assert packs._parse_pack(tmp_path).maps[0].name=='new'
    extra=tmp_path/'locations/extra.json'
    extra.write_text('[{"name":"Second","map_locations":[{"map":"new","x":4,"y":4}]}]')
    assert any(m.location_name=='Second' for m in packs._parse_pack(tmp_path).markers)
    extra.unlink()
    assert all(m.location_name!='Second' for m in packs._parse_pack(tmp_path).markers)


def test_zip_cache_and_streaming_image(tmp_path):
    """Handle test zip cache and streaming image."""
    folder=tmp_path/'folder'; make_pack(folder)
    archive=tmp_path/'pack.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for p in folder.rglob('*'):
            if p.is_file(): z.write(p,'nested/'+p.relative_to(folder).as_posix())
    pack=packs._parse_pack(archive)
    with patch.object(packs,'_parse_pack_uncached',side_effect=AssertionError('reparsed')):
        assert packs._parse_pack(archive).maps[0].name=='test'
    with open_pack_image(pack,'map.png') as im:
        assert im.getpixel((0,0))==(255,0,0)


def test_large_map_install_is_header_only(tmp_path,monkeypatch):
    """Handle test large map install is header only."""
    pack=make_pack(tmp_path/'pack')
    monkeypatch.setattr(packs,'LARGE_MAP_PIXELS',100)
    monkeypatch.setattr(packs,'map_cache_root',lambda:tmp_path/'cache')
    with patch.object(Image.Image,'convert',side_effect=AssertionError('decoded large map')):
        assert packs.build_pack_zoom_cache(pack.source)==(0,0)
    manifest=json.loads(packs._cache_manifest_path(pack.source).read_text())
    assert len(manifest['deferred_maps'])==1
    assert not list((tmp_path/'cache').rglob('*.png'))


def test_small_map_still_builds_zoom_cache(tmp_path,monkeypatch):
    """Handle test small map still builds zoom cache."""
    pack=make_pack(tmp_path/'pack')
    monkeypatch.setattr(packs,'map_cache_root',lambda:tmp_path/'cache')
    monkeypatch.setattr(packs,'ZOOM_CACHE_LEVELS',(50,100))
    assert packs.build_pack_zoom_cache(pack.source)==(2,2)
    assert packs.cached_map_path(pack.source,'map.png',50).is_file()


def test_image_cache_budget_and_recency():
    """Handle test image cache budget and recency."""
    cache={}; image=Image.new('RGBA',(10,10))
    remember_image(cache,'a',image,budget=800)
    remember_image(cache,'b',image,budget=800)
    assert cached_image(cache,'a') is image
    remember_image(cache,'c',image,budget=800)
    assert list(cache)==['a','c']
    remember_image(cache,'huge',Image.new('RGBA',(30,30)),budget=800)
    assert 'huge' not in cache


def test_image_identity_changes_and_hash_is_reused(tmp_path):
    """Handle test image identity changes and hash is reused."""
    pack=make_pack(tmp_path)
    before=asset_key(pack,'map.png',50)
    digest=image_hash(tmp_path/'map.png')
    with patch('builtins.open',side_effect=AssertionError('read source twice')):
        assert image_hash(tmp_path/'map.png')==digest
    Image.new('RGB',(25,17),'blue').save(tmp_path/'map.png')
    assert asset_key(pack,'map.png',50)!=before
    assert image_hash(tmp_path/'map.png')!=digest


def test_hidden_map_does_not_schedule_decode():
    """Handle test hidden map does not schedule decode."""
    app=WayFinderApp.__new__(WayFinderApp)
    app._closing=False; app.current_page='Dashboard'; app.map_canvas=object()
    app._request_map_render()
    assert app._map_render_deferred


def test_preview_preserves_coordinates():
    """Handle test preview preserves coordinates."""
    _,image=render_result(Image.new('RGBA',(800,400)),50)
    preview,dimensions=image.info['wayfinder_preview']
    assert preview.size==(184,92)
    assert dimensions==(1600,800)


def test_worker_renders_and_reuses_requested_zoom(tmp_path,monkeypatch):
    """Handle test worker renders and reuses requested zoom."""
    pack=make_pack(tmp_path/'pack')
    monkeypatch.setattr(packs,'map_cache_root',lambda:tmp_path/'cache')
    app=WayFinderApp.__new__(WayFinderApp)
    app._closing=False; app.events=queue.Queue(); app.map_render_generation=1
    app._map_render_condition=threading.Condition(); app._map_scaled_cache_lock=threading.Lock(); app._map_source_cache_lock=threading.Lock()
    app.map_scaled_cache={}; app.map_source_cache={}
    app._prefetch_neighbor_zoom_images=lambda *args:None
    key=asset_key(pack,'map.png',50)
    app._map_render_pending=(1,key,pack,pack.maps[0],50,0,0,False)
    worker=threading.Thread(target=app._map_render_worker_loop,daemon=True); worker.start()
    try:
        kind,payload=app.events.get(timeout=10)
        assert kind=='map_render_done', payload
        assert payload[2][1].size==(12,8)
        assert key in app.map_scaled_cache
        with patch('wayfinder.app.app.open_pack_image',side_effect=AssertionError('decoded twice')):
            with app._map_render_condition:
                app._map_render_pending=(1,key,pack,pack.maps[0],50,0,0,False)
                app._map_render_condition.notify()
            kind,payload=app.events.get(timeout=10)
            assert kind=='map_render_done',payload
    finally:
        with app._map_render_condition:
            app._closing=True; app._map_render_condition.notify()
        worker.join(timeout=10)


def test_invalid_archive_keeps_discovery_nonfatal(tmp_path):
    """Handle test invalid archive keeps discovery nonfatal."""
    archive=tmp_path/'broken.zip'
    archive.write_bytes(b'not a zip')
    assert packs._parse_pack(archive) is None
