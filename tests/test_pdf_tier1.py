"""Tier-1 PDF feature tests: crop/resize, invert, headers/footers, fingerprint."""
import fitz
import pytest
from pathlib import Path

from cachyview.backends import pdf as pb


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "src.pdf"
    d = fitz.open()
    for _ in range(3):
        page = d.new_page(width=595, height=842)
        page.insert_text((72, 72), "CachyView test page")
    d.save(str(p))
    d.close()
    return p


def test_crop_resize_margins(doc, tmp_path):
    out = tmp_path / "crop.pdf"
    pb.crop_resize_pages(doc, out, margins=(20, 20, 20, 20))
    d = fitz.open(out)
    cb = d[0].cropbox
    assert cb.width == pytest.approx(595 - 40)
    assert cb.height == pytest.approx(842 - 40)
    d.close()


def test_crop_resize_page_size(doc, tmp_path):
    out = tmp_path / "size.pdf"
    pb.crop_resize_pages(doc, out, page_size="A4")
    d = fitz.open(out)
    assert (d[0].rect.width, d[0].rect.height) == (595, 842)
    d.close()


def test_invert_colours(doc, tmp_path):
    out = tmp_path / "inv.pdf"
    pb.invert_colours(doc, out)
    d = fitz.open(out)
    assert d.page_count == 3
    # inverted page now carries an embedded image covering it
    assert d[0].get_images(full=True)
    d.close()


def test_headers_footers(doc, tmp_path):
    out = tmp_path / "hf.pdf"
    pb.add_headers_footers(doc, out, header="Top",
                            footer="Bottom", page_numbers=True)
    d = fitz.open(out)
    txt = d[0].get_text()
    assert "Top" in txt and "Bottom" in txt and "1" in txt
    d.close()


def test_fingerprint(doc):
    sums = pb.fingerprint(doc)
    assert set(sums) == {"sha256", "sha1", "md5"}
    assert len(sums["sha256"]) == 64
    # stable across calls
    assert sums == pb.fingerprint(doc)
