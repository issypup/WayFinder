"""Provide test installed maps manager support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP=Path(__file__).resolve().parents[2]/"wayfinder"/"app"/"app.py"

def test_installed_maps_has_own_navigation_and_page():
    """Handle test installed maps has own navigation and page."""
    source=combined_app_source()
    assert '"Installed Maps":"▤  Installed Maps"' in source
    assert 'def _build_installed_maps(self):' in source
    assert 'self._build_map(); self._build_installed_maps(); self._build_pack_converter()' in source


def test_map_header_no_longer_owns_install_management_controls():
    """Handle test map header no longer owns install management controls."""
    source=combined_app_source()
    start=source.index('def _build_map(self):')
    next_method=source.find('\n    def ',start+10)
    assert next_method > start
    map_block=source[start:next_method]
    assert 'command=self._install_map_pack' not in map_block
    assert 'command=self._open_map_pack_folder' not in map_block
    assert 'command=self._revalidate_active_map_pack' not in map_block
    assert 'command=self._remove_map_pack' not in map_block

def test_installed_maps_supports_auto_and_manual_pack_selection():
    """Handle test installed maps supports auto and manual pack selection."""
    source=combined_app_source()
    assert 'self.active_map_pack_choice = tk.StringVar' in source
    assert 'def _preferred_map_pack(self, live, game):' in source
    assert 'labels=["Auto"]+self._installed_map_pack_labels()' in source
    assert 'pack,matches=self._preferred_map_pack(live,self.snapshot.game)' in source
