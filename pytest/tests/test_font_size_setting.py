"""Text-size accessibility setting: named fonts drive every piece of UI text."""
import pytest
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from wayfinder.app.core.source_layout import combined_app_source
from wayfinder.app.ui.appearance import (
    FONT_SIZE_DEFAULT, FONT_SIZE_MAX, FONT_SIZE_MIN, TK_STANDARD_FONTS,
    apply_named_fonts, clamp_font_size, font_specs,
)


def test_clamp_font_size_handles_bad_and_out_of_range_values():
    """Stored settings may be missing, garbage, or from an older/wider range."""
    assert clamp_font_size(None) == FONT_SIZE_DEFAULT
    assert clamp_font_size("nope") == FONT_SIZE_DEFAULT
    assert clamp_font_size("14") == 14
    assert clamp_font_size(1) == FONT_SIZE_MIN
    assert clamp_font_size(99) == FONT_SIZE_MAX
    assert FONT_SIZE_MIN < FONT_SIZE_DEFAULT < FONT_SIZE_MAX
    assert FONT_SIZE_MAX >= 24, "large sizes must be available for low-vision users"


def test_every_named_font_grows_with_the_base_size():
    """No text role may be pinned to a fixed size; all must track the setting."""
    small, large = font_specs(FONT_SIZE_MIN), font_specs(FONT_SIZE_MAX)
    assert set(small) == set(large)
    for name in small:
        assert large[name]["size"] > small[name]["size"], name
    assert font_specs(10)["WayFinderBody"]["size"] == 10
    assert font_specs(10)["WayFinderTitle"]["size"] == 22
    assert font_specs(10)["WayFinderSmall"]["size"] == 9
    # Floors keep the smallest map text legible at the minimum setting.
    assert font_specs(FONT_SIZE_MIN)["WayFinderMarkerCount"]["size"] >= 6


def test_app_source_no_longer_bakes_font_tuples_into_widgets():
    """Literal font tuples freeze a size at build time and ignore later changes."""
    source = combined_app_source()
    assert 'font=("Segoe UI' not in source
    assert 'font=("Consolas' not in source
    for line in source.splitlines():
        if "font=" in line or "label_font=" in line:
            assert "font_size.get()" not in line, line.strip()
    assert '"WayFinderBody"' in source and '"WayFinderMarkerLabel"' in source


def _tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    return root


def test_resizing_named_fonts_updates_live_widgets_and_canvas_text():
    """Widgets, tree tags, Tk default fonts and canvas items must follow one resize."""
    root = _tk_root()
    try:
        apply_named_fonts(root, 10)
        assert tkfont.nametofont("WayFinderBody", root=root).cget("size") == 10
        for name in TK_STANDARD_FONTS:
            assert tkfont.nametofont(name, root=root).cget("size") == 10
        # Mirror _configure_style: classic Tk widgets pick the named font up
        # from the option database.
        root.option_add("*Font", "WayFinderBody")
        style = ttk.Style(root)
        style.configure("Probe.TLabel", font="WayFinderBody")
        label = ttk.Label(root, text="status", style="Probe.TLabel")
        plain_text = tk.Text(root)
        canvas = tk.Canvas(root)
        item = canvas.create_text(0, 0, text="Marker", font="WayFinderMarkerLabel")
        tree = ttk.Treeview(root)
        tree.tag_configure("recent", font="WayFinderSemibold")
        # Headless X servers without scalable fonts resolve every family to a
        # fixed bitmap font whose pixel size never changes; only check pixel
        # measurements when the platform actually honours the requested size.
        scalable = tkfont.nametofont("WayFinderBody", root=root).actual("size") == 10
        before_label = tkfont.Font(root=root, font=style.lookup("Probe.TLabel", "font")).measure("status")
        before_marker = tkfont.Font(root=root, font=canvas.itemcget(item, "font")).measure("Marker")
        before_text = tkfont.Font(root=root, font=plain_text.cget("font")).measure("console")

        apply_named_fonts(root, 20)

        # Every widget still points at the shared named font, so the resize reaches it.
        assert style.lookup("Probe.TLabel", "font") == "WayFinderBody"
        assert canvas.itemcget(item, "font") == "WayFinderMarkerLabel"
        assert plain_text.cget("font") == "WayFinderBody", "tk.Text must inherit the named font via the option database / TkTextFont"
        assert tkfont.nametofont("WayFinderBody", root=root).cget("size") == 20
        assert tkfont.nametofont("WayFinderMarkerLabel", root=root).cget("size") == 19
        assert tkfont.nametofont("TkDefaultFont", root=root).cget("size") == 20
        assert str(tree.tag_configure("recent", "font")) == "WayFinderSemibold"
        assert tkfont.nametofont("WayFinderSemibold", root=root).cget("size") == 20
        assert label.winfo_exists()
        if scalable:
            assert tkfont.Font(root=root, font=style.lookup("Probe.TLabel", "font")).measure("status") > before_label
            assert tkfont.Font(root=root, font=canvas.itemcget(item, "font")).measure("Marker") > before_marker
            assert tkfont.Font(root=root, font=plain_text.cget("font")).measure("console") > before_text
    finally:
        root.destroy()


def test_apply_named_fonts_is_idempotent():
    """Reapplying must reconfigure existing fonts, not fail because they exist."""
    root = _tk_root()
    try:
        apply_named_fonts(root, 12)
        apply_named_fonts(root, 12)
        apply_named_fonts(root, 16)
        assert tkfont.nametofont("WayFinderKpi", root=root).cget("size") == 26
    finally:
        root.destroy()
