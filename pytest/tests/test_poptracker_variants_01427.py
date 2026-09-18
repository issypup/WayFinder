"""Provide test poptracker variants 01427 support."""
import json
import zipfile
from pathlib import Path

from wayfinder.maps.converter import convert_poptracker_pack
from wayfinder.maps.packs import _parse_pack, load_pack_variant


def _write_json(path: Path, value):
    """Handle write json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_poptracker_manifest_variants_are_preserved_and_selectable(tmp_path):
    """Handle test poptracker manifest variants are preserved and selectable."""
    source_root = tmp_path / "source"
    _write_json(source_root / "manifest.json", {
        "name": "Variant Test",
        "variants": {
            "standard": {"display_name": "Standard Maps", "flags": ["ap"]},
            "variant_extra": {"display_name": "Extra Maps", "flags": ["ap"]},
        },
    })
    _write_json(source_root / "maps" / "maps.json", [
        {"name": "base", "img": "images/base.png"},
    ])
    _write_json(source_root / "variant_extra" / "maps" / "maps.json", [
        {"name": "base", "img": "images/base.png"},
        {"name": "extra", "img": "images/extra.png"},
    ])
    _write_json(source_root / "locations" / "locations.json", [{
        "name": "Check",
        "sections": [{"name": "Check"}],
        "map_locations": [{"map": "base", "x": 1, "y": 2}],
    }])
    (source_root / "images").mkdir()
    (source_root / "images" / "base.png").write_bytes(b"not-an-image-but-converter-preserves-it")
    (source_root / "images" / "extra.png").write_bytes(b"not-an-image-but-converter-preserves-it")

    source_zip = tmp_path / "source.zip"
    with zipfile.ZipFile(source_zip, "w") as zf:
        for path in source_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source_root).as_posix())

    converted = tmp_path / "converted.zip"
    result = convert_poptracker_pack(source_zip, converted)
    assert result.output == converted

    with zipfile.ZipFile(converted) as zf:
        variants = json.loads(zf.read("wayfinder_variants.json"))
        assert variants["default"] == "standard"
        assert {v["uid"] for v in variants["variants"]} == {"standard", "variant_extra"}
        assert "variants/variant_extra/maps/maps.json" in zf.namelist()

    standard = _parse_pack(converted)
    assert standard is not None
    assert standard.variant_uid == "standard"
    assert [m.name for m in standard.maps] == ["base"]
    assert standard.variants["variant_extra"] == "Extra Maps"

    extra = load_pack_variant(standard, "variant_extra")
    assert extra.variant_uid == "variant_extra"
    assert [m.name for m in extra.maps] == ["base", "extra"]
