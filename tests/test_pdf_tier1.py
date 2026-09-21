"""Tier-1 PDF feature tests: crop/resize, invert, headers/footers, fingerprint."""
import shutil

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


@pytest.mark.skipif(not shutil.which("gs"), reason="needs ghostscript")
def test_to_pdfa_produces_readable_pdf(doc, tmp_path):
    out = tmp_path / "archival.pdf"
    pb.to_pdfa(doc, out, level=2)
    assert out.is_file() and out.stat().st_size > 0
    d = fitz.open(out)
    assert d.page_count == 3
    d.close()


def test_to_pdfa_rejects_bad_level(doc, tmp_path):
    with pytest.raises(pb.PdfError):
        pb.to_pdfa(doc, tmp_path / "x.pdf", level=9)


@pytest.mark.skipif(not shutil.which("soffice"), reason="needs LibreOffice")
def test_to_docx_creates_word_file(doc, tmp_path):
    target = pb.to_docx(doc, tmp_path)
    assert target.suffix == ".docx" and target.is_file()
    assert target.stat().st_size > 0
