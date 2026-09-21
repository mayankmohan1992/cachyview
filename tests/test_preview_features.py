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


def test_levels_maps_black_and_white():
    img = Image.new("RGB", (3, 1))
    img.putdata([(10, 10, 10), (128, 128, 128), (200, 200, 200)])
    out = im.apply_ops(img, [im.Op("levels", {"black": 10, "white": 200})])
    assert out.getpixel((0, 0)) == (0, 0, 0)
    assert out.getpixel((2, 0)) == (255, 255, 255)
    assert 155 <= out.getpixel((1, 0))[0] <= 161


def test_levels_gamma_brightens():
    img = Image.new("RGB", (1, 1), (100, 100, 100))
    out = im.apply_ops(img, [im.Op("levels", {"gamma": 2.0})])
    assert out.getpixel((0, 0))[0] > 100


def test_curves_identity_and_s_curve():
    img = Image.new("RGB", (3, 1))
    img.putdata([(30, 30, 30), (128, 128, 128), (220, 220, 220)])
    identity = im.apply_ops(img, [im.Op("curves", {"points": [(0, 0), (255, 255)]})])
    assert identity.getpixel((1, 0)) == (128, 128, 128)
    lifted = im.apply_ops(img, [im.Op("curves", {"points": [(0, 0), (128, 180), (255, 255)]})])
    assert lifted.getpixel((1, 0))[0] > 128


def test_curves_needs_two_points():
    with pytest.raises(im.ImageError):
        im.apply_ops(Image.new("RGB", (2, 2)), [im.Op("curves", {"points": [(0, 0)]})])


def test_redeye_desaturates_red_pupil():
    img = Image.new("RGB", (3, 1))
    img.putdata([(220, 30, 30), (30, 220, 30), (40, 40, 40)])
    out = im.apply_ops(img, [im.Op("redeye", {"threshold": 1.5, "strength": 1.0})])
    r, g, b = out.getpixel((0, 0))
    assert r == (g + b) // 2 and r < 220
    assert out.getpixel((1, 0)) == (30, 220, 30)
    assert out.getpixel((2, 0)) == (40, 40, 40)


def test_redeye_leaves_alpha_alone():
    img = Image.new("RGBA", (2, 1), (220, 30, 30, 123))
    out = im.apply_ops(img, [im.Op("redeye", {"box": (0, 0, 2, 1)})])
    assert out.getpixel((0, 0))[3] == 123


def test_minify_json():
    assert tb.minify('{"a": 1, "b": [2]}', "json") == '{"a":1,"b":[2]}'


def test_validate_json_ok():
    assert tb.validate('{"x": true}', "json") == ""


def test_validate_json_bad():
    with pytest.raises(ValueError):
        tb.validate("{", "json")


def test_pretty_print_yaml():
    out = tb.pretty_print("b: 2\na: 1\n", "yaml")
    assert "a: 1" in out and "b: 2" in out
    assert out.count("\n") >= 2


def test_validate_yaml_bad():
    with pytest.raises(ValueError):
        tb.validate("a: [1, 2\n", "yaml")


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
