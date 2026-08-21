"""New Preview-killer backends: extra image ops, text helpers, PDF search, archives."""
import pytest
from PIL import Image

from cachyview.backends import image as im
from cachyview.backends import text as tb


def test_gamma_and_sepia_keep_size(tmp_path):
    img = Image.new("RGB", (40, 20), (80, 120, 200))
    out = im.apply_ops(img, [im.Op("gamma", {"value": 1.4}), im.Op("sepia")])
    assert out.size == (40, 20)


def test_scale_half(tmp_path):
    img = Image.new("RGB", (100, 50), (10, 20, 30))
    out = im.apply_ops(img, [im.Op("scale", {"factor": 0.5})])
    assert out.size == (50, 25)


def test_canvas_center():
    img = Image.new("RGB", (10, 10), (255, 0, 0))
    out = im.apply_ops(img, [im.Op("canvas", {"width": 20, "height": 20,
                                              "anchor": "center", "fill": "#000000"})])
    assert out.size == (20, 20)


def test_draw_rectangle():
    img = Image.new("RGB", (80, 80), (255, 255, 255))
    out = im.apply_ops(img, [im.Op("draw", {"kind": "rectangle",
                                            "points": [(10, 10), (40, 40)],
                                            "color": "#ff0000"})])
    assert out.size == (80, 80)


def test_histograms():
    img = Image.new("RGB", (16, 16), (12, 34, 56))
    h = im.histograms(img)
    assert len(h["luma"]) == 256
    assert sum(h["r"]) == 16 * 16


def test_minify_json():
    assert tb.minify('{"a": 1, "b": [2]}', "json") == '{"a":1,"b":[2]}'


def test_validate_json_ok():
    assert tb.validate('{"x": true}', "json") == ""


def test_validate_json_bad():
    with pytest.raises(ValueError):
        tb.validate("{", "json")


def test_unified_diff():
    diff = tb.unified_diff("a\n", "b\n", "a.txt", "b.txt")
    assert "-a" in diff and "+b" in diff


def test_hex_dump_offset():
    text = tb.hex_dump(b"AB", offset=16)
    assert text.startswith("00000010")
    assert "41 42" in text


def test_csv_rows():
    header, rows = tb.csv_rows("a,b\n1,2\n3,4\n")
    assert header == ["a", "b"]
    assert rows == [["1", "2"], ["3", "4"]]


@pytest.mark.skipif(pytest.importorskip("fitz") is None, reason="pymupdf")
def test_pdf_search_and_words(tmp_path):
    import fitz
    from cachyview.backends import pdf as pb
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 120), "UniqueNeedleWord", fontsize=14)
    p = tmp_path / "s.pdf"
    doc.save(str(p))
    doc.close()
    hits = pb.search_text(p, "UniqueNeedleWord")
    assert hits and hits[0][0] == 1
    words = pb.page_words(p, 1)
    assert any("Unique" in w[4] for w in words)
