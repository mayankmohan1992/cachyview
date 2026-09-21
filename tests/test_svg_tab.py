"""SVG tab: renders a valid document and survives malformed source."""
from pathlib import Path

from cachyview.core.mime import Kind, detect_kind
from cachyview.ui.svg_tab import SvgTab

VALID = ('<?xml version="1.0"?>'
         '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
         '<rect width="20" height="20" fill="red"/></svg>')


def test_svg_routes_to_svg_kind(tmp_path):
    p = tmp_path / "a.svg"
    p.write_text(VALID, encoding="utf-8")
    assert detect_kind(p) == Kind.SVG


def test_svg_tab_renders_and_edits(tmp_path, app):
    p = tmp_path / "a.svg"
    p.write_text(VALID, encoding="utf-8")
    tab = SvgTab(p)
    assert tab.preview.renderer().isValid()
    assert not tab.is_modified()
    tab.editor.setPlainText(VALID.replace("red", "blue"))
    assert tab.is_modified()
    assert tab.save()
    assert "blue" in p.read_text(encoding="utf-8")
    assert not tab.is_modified()


def test_svg_tab_tolerates_malformed_source(tmp_path, app):
    p = tmp_path / "bad.svg"
    p.write_text("<svg><this is not valid</svg>", encoding="utf-8")
    tab = SvgTab(p)          # must not raise
    assert tab.error != ""
