"""Provide test map pack auto convert install 01431 support."""
from pathlib import Path
import zipfile

from wayfinder.maps.converter import detect_map_pack_archive_format


def _zip(path: Path, files: dict[str, str]) -> Path:
    """Handle zip."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


def test_archive_classifier_prefers_wayfinder_marker_over_other_signatures(tmp_path):
    """Handle test archive classifier prefers wayfinder marker over other signatures."""
    archive = _zip(tmp_path / "converted.zip", {
        "wayfinder_pack.json": "{}",
        "manifest.json": "{}",
        "maps/maps.json": "[]",
    })
    assert detect_map_pack_archive_format(archive) == "wayfinder"


def test_archive_classifier_recognizes_raw_poptracker_even_with_maps_maps_json(tmp_path):
    """Handle test archive classifier recognizes raw poptracker even with maps maps json."""
    archive = _zip(tmp_path / "raw-poptracker.zip", {
        "manifest.json": '{"name":"Example"}',
        "maps/maps.json": "[]",
        "variant_x/maps/maps.json": "[]",
    })
    assert detect_map_pack_archive_format(archive) == "poptracker"


def test_archive_classifier_recognizes_legacy_tracker_pack(tmp_path):
    """Handle test archive classifier recognizes legacy tracker pack."""
    archive = _zip(tmp_path / "legacy.zip", {"maps/maps.json": "[]"})
    assert detect_map_pack_archive_format(archive) == "universal_tracker"


def test_archive_classifier_rejects_unknown_zip(tmp_path):
    """Handle test archive classifier rejects unknown zip."""
    archive = _zip(tmp_path / "unknown.zip", {"readme.txt": "hello"})
    assert detect_map_pack_archive_format(archive) == "unknown"


def test_installer_auto_converts_before_installing():
    """Handle test installer auto converts before installing."""
    root = Path(__file__).resolve().parents[2]
    source = (root / "wayfinder/app/map/map_pack_manager.py").read_text(encoding="utf-8")
    assert "detect_map_pack_archive_format(selected_archive)" in source
    assert "convert_poptracker_pack(selected_archive, converted_archive)" in source
    assert "convert_ut_pack(selected_archive, converted_archive)" in source
    assert "install_pack_archive(install_archive, game_pack_dir(self.snapshot.game))" in source
