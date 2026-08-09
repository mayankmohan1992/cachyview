"""PDF backend tests.  Every test builds and inspects a real PDF."""
import shutil
import subprocess

import pytest

from cachyview.backends import pdf

fitz = pytest.importorskip("fitz")
pikepdf = pytest.importorskip("pikepdf")

HAVE_GS = shutil.which("gs") is not None
HAVE_QPDF = shutil.which("qpdf") is not None
HAVE_OCR = shutil.which("ocrmypdf") is not None


def make_pdf(path, pages=3, text="Page"):
    """A real multi-page PDF with selectable text."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"{text} {i + 1}", fontsize=24)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def sample(tmp_path):
    return make_pdf(tmp_path / "sample.pdf", 3)


@pytest.fixture
def big(tmp_path):
    return make_pdf(tmp_path / "big.pdf", 10)


# --- page ranges ----------------------------------------------------------

@pytest.mark.parametrize("spec,total,want", [
    ("1", 5, [1]),
    ("1-3", 5, [1, 2, 3]),
    ("1,3,5", 5, [1, 3, 5]),
    ("2-", 5, [2, 3, 4, 5]),
    ("-3", 5, [1, 2, 3]),
    ("", 3, [1, 2, 3]),
    ("3,1,2", 3, [1, 2, 3]),
    ("1-2,2-3", 3, [1, 2, 3]),
])
def test_parse_ranges(spec, total, want):
    assert pdf.parse_ranges(spec, total) == want


@pytest.mark.parametrize("spec", ["0", "9", "4-2", "abc", "1-99", "-", "1,,x"])
def test_parse_ranges_invalid(spec):
    with pytest.raises(pdf.PdfError):
        pdf.parse_ranges(spec, 5)


# --- inspection -----------------------------------------------------------

def test_info(sample):
    got = pdf.info(sample)
    assert got.page_count == 3
    assert len(got.pages) == 3
    assert got.has_text
    assert got.file_size > 0
    assert not got.encrypted
    assert got.pages[0].number == 1
    assert got.pages[0].width > 0


def test_page_geometry_a4ish(sample):
    page = pdf.info(sample).pages[0]
    w_mm, h_mm = page.size_mm
    assert 200 < w_mm < 220 and 280 < h_mm < 300
    assert not page.is_landscape


def test_info_missing_file(tmp_path):
    with pytest.raises(pdf.PdfError):
        pdf.info(tmp_path / "nope.pdf")


def test_extract_text(sample):
    text = pdf.extract_text(sample)
    assert "Page 1" in text and "Page 3" in text


def test_extract_text_single_page(sample):
    text = pdf.extract_text(sample, pages=[2])
    assert "Page 2" in text and "Page 1" not in text


def test_render_page_returns_png(sample):
    data = pdf.render_page(sample, 1, dpi=72)
    assert data.startswith(b"\x89PNG")


def test_render_page_dpi_affects_size(sample):
    small = pdf.render_page(sample, 1, dpi=50)
    large = pdf.render_page(sample, 1, dpi=150)
    assert len(large) > len(small)


def test_render_invalid_page(sample):
    with pytest.raises(pdf.PdfError):
        pdf.render_page(sample, 99)


# --- merge / split --------------------------------------------------------

def test_merge(tmp_path, sample):
    other = make_pdf(tmp_path / "other.pdf", 2, text="Other")
    out = pdf.merge([sample, other], tmp_path / "merged.pdf")
    assert pdf.info(out).page_count == 5
    text = pdf.extract_text(out)
    assert "Page 1" in text and "Other 1" in text


def test_merge_preserves_order(tmp_path, sample):
    other = make_pdf(tmp_path / "other.pdf", 1, text="ZZZ")
    out = pdf.merge([other, sample], tmp_path / "m2.pdf")
    assert "ZZZ 1" in pdf.extract_text(out, pages=[1])


def test_merge_empty_raises(tmp_path):
    with pytest.raises(pdf.PdfError):
        pdf.merge([], tmp_path / "x.pdf")


def test_split_every_page(tmp_path, sample):
    parts = pdf.split(sample, tmp_path / "parts", every=1)
    assert len(parts) == 3
    assert all(pdf.info(p).page_count == 1 for p in parts)


def test_split_in_twos(tmp_path, big):
    parts = pdf.split(big, tmp_path / "p2", every=2)
    assert len(parts) == 5
    assert all(pdf.info(p).page_count == 2 for p in parts)


def test_split_uneven_last_chunk(tmp_path, sample):
    parts = pdf.split(sample, tmp_path / "p3", every=2)
    assert [pdf.info(p).page_count for p in parts] == [2, 1]


def test_split_by_ranges(tmp_path, big):
    parts = pdf.split(big, tmp_path / "p4", ranges="1-3;5-6")
    assert [pdf.info(p).page_count for p in parts] == [3, 2]


# --- page manipulation ----------------------------------------------------

def test_extract_pages(tmp_path, big):
    out = pdf.extract_pages(big, tmp_path / "ex.pdf", "2,4,6")
    assert pdf.info(out).page_count == 3
    assert "Page 2" in pdf.extract_text(out, pages=[1])


def test_delete_pages(tmp_path, sample):
    out = pdf.delete_pages(sample, tmp_path / "del.pdf", "2")
    assert pdf.info(out).page_count == 2
    text = pdf.extract_text(out)
    assert "Page 2" not in text and "Page 1" in text


def test_delete_all_pages_refused(tmp_path, sample):
    with pytest.raises(pdf.PdfError, match="every page"):
        pdf.delete_pages(sample, tmp_path / "d.pdf", "1-3")


def test_rotate_pages(tmp_path, sample):
    out = pdf.rotate_pages(sample, tmp_path / "rot.pdf", angle=90)
    assert all(p.rotation == 90 for p in pdf.info(out).pages)


def test_rotate_is_cumulative(tmp_path, sample):
    once = pdf.rotate_pages(sample, tmp_path / "r1.pdf", angle=90)
    twice = pdf.rotate_pages(once, tmp_path / "r2.pdf", angle=90)
    assert all(p.rotation == 180 for p in pdf.info(twice).pages)


def test_rotate_single_page(tmp_path, sample):
    out = pdf.rotate_pages(sample, tmp_path / "r3.pdf", angle=270, ranges="2")
    rots = [p.rotation for p in pdf.info(out).pages]
    assert rots == [0, 270, 0]


def test_rotate_rejects_odd_angle(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.rotate_pages(sample, tmp_path / "r4.pdf", angle=45)


def test_reorder_pages(tmp_path, sample):
    out = pdf.reorder_pages(sample, tmp_path / "ord.pdf", [3, 1, 2])
    assert "Page 3" in pdf.extract_text(out, pages=[1])
    assert "Page 1" in pdf.extract_text(out, pages=[2])


def test_reorder_rejects_incomplete_order(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.reorder_pages(sample, tmp_path / "o2.pdf", [1, 2])


# --- apply_layout (page organiser backend) --------------------------------

def test_apply_layout_duplicates_a_page(tmp_path, sample):
    out = tmp_path / "dup.pdf"
    pdf.apply_layout(sample, out, [(1, 0), (1, 0), (2, 0)])
    assert pdf.info(out).page_count == 3
    assert pdf.extract_text(out, [1]).strip() == pdf.extract_text(out, [2]).strip()


def test_apply_layout_drops_pages(tmp_path, sample):
    out = tmp_path / "drop.pdf"
    pdf.apply_layout(sample, out, [(2, 0)])
    info = pdf.info(out)
    assert info.page_count == 1
    assert "2" in pdf.extract_text(out, [1])


def test_apply_layout_sets_absolute_rotation(tmp_path, sample):
    out = tmp_path / "rot.pdf"
    pdf.apply_layout(sample, out, [(1, 90), (2, 270), (3, 0)])
    assert [p.rotation for p in pdf.info(out).pages] == [90, 270, 0]


def test_apply_layout_rejects_empty(tmp_path, sample):
    with pytest.raises(pdf.PdfError, match="at least one page"):
        pdf.apply_layout(sample, tmp_path / "empty.pdf", [])


def test_apply_layout_rejects_out_of_range(tmp_path, sample):
    with pytest.raises(pdf.PdfError, match="outside"):
        pdf.apply_layout(sample, tmp_path / "bad.pdf", [(99, 0)])


def test_apply_layout_keeps_text_selectable(tmp_path, sample):
    """Structural copy, not a re-render: text must survive."""
    out = tmp_path / "sel.pdf"
    pdf.apply_layout(sample, out, [(3, 0), (1, 0)])
    assert pdf.extract_text(out, [1]).strip()
    assert pdf.extract_text(out, [2]).strip()


def test_apply_layout_on_encrypted_source(tmp_path, sample):
    enc = tmp_path / "enc.pdf"
    pdf.protect(sample, enc, user_password="pw")
    out = tmp_path / "enc_out.pdf"
    pdf.apply_layout(enc, out, [(2, 90), (1, 0)], password="pw")
    assert [p.rotation for p in pdf.info(out).pages] == [90, 0]


def test_reorder_rejects_duplicates(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.reorder_pages(sample, tmp_path / "o3.pdf", [1, 1, 2])


# --- security -------------------------------------------------------------

def test_protect_then_needs_password(tmp_path, sample):
    out = pdf.protect(sample, tmp_path / "enc.pdf", user_password="hunter2")
    with pytest.raises(pdf.PdfPasswordRequired):
        pdf.info(out)


def test_protect_opens_with_password(tmp_path, sample):
    out = pdf.protect(sample, tmp_path / "enc.pdf", user_password="hunter2")
    assert pdf.info(out, password="hunter2").page_count == 3


def test_wrong_password_raises(tmp_path, sample):
    out = pdf.protect(sample, tmp_path / "enc.pdf", user_password="hunter2")
    with pytest.raises(pdf.PdfWrongPassword):
        pdf.info(out, password="nope")


def test_unlock_removes_encryption(tmp_path, sample):
    enc = pdf.protect(sample, tmp_path / "enc.pdf", user_password="pw")
    out = pdf.unlock(enc, tmp_path / "free.pdf", password="pw")
    assert pdf.info(out).page_count == 3


def test_unlock_wrong_password(tmp_path, sample):
    enc = pdf.protect(sample, tmp_path / "enc.pdf", user_password="pw")
    with pytest.raises(pdf.PdfWrongPassword):
        pdf.unlock(enc, tmp_path / "f2.pdf", password="bad")


def test_protect_requires_password(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.protect(sample, tmp_path / "e.pdf", user_password="")


def test_operations_on_encrypted_need_password(tmp_path, sample):
    enc = pdf.protect(sample, tmp_path / "enc.pdf", user_password="pw")
    with pytest.raises(pdf.PdfPasswordRequired):
        pdf.split(enc, tmp_path / "sp")
    parts = pdf.split(enc, tmp_path / "sp2", password="pw")
    assert len(parts) == 3


# --- compression ----------------------------------------------------------

@pytest.mark.skipif(not HAVE_GS, reason="needs ghostscript")
def test_compress_shrinks_image_heavy_pdf(tmp_path):
    from PIL import Image
    img = tmp_path / "photo.jpg"
    p = Image.new("RGB", (1600, 1200))
    for x in range(0, 1600, 4):
        for y in range(0, 1200, 4):
            p.paste((x % 256, y % 256, (x + y) % 256), (x, y, x + 4, y + 4))
    p.save(img, quality=98)

    doc = fitz.open()
    for _ in range(4):
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 595, 842), filename=str(img))
    src = tmp_path / "heavy.pdf"
    doc.save(str(src))
    doc.close()

    out, before, after = pdf.compress(src, tmp_path / "small.pdf", tier="screen")
    assert out.is_file()
    assert after < before
    assert pdf.info(out).page_count == 4


@pytest.mark.skipif(not HAVE_GS, reason="needs ghostscript")
def test_compress_tiers_ordered(tmp_path, sample):
    outs = {}
    for tier in ("screen", "ebook", "printer"):
        out, _, after = pdf.compress(sample, tmp_path / f"{tier}.pdf", tier=tier)
        outs[tier] = after
        assert pdf.info(out).page_count == 3
    assert all(v > 0 for v in outs.values())


def test_compress_unknown_tier(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.compress(sample, tmp_path / "x.pdf", tier="ludicrous")


# --- conversion -----------------------------------------------------------

def test_to_images(tmp_path, sample):
    out = pdf.to_images(sample, tmp_path / "imgs", dpi=72)
    assert len(out) == 3
    assert all(p.is_file() and p.suffix == ".png" for p in out)


def test_to_images_jpeg(tmp_path, sample):
    out = pdf.to_images(sample, tmp_path / "j", dpi=72, fmt="jpg")
    assert out[0].read_bytes().startswith(b"\xff\xd8\xff")


def test_to_images_range(tmp_path, big):
    out = pdf.to_images(big, tmp_path / "r", dpi=50, ranges="2-4")
    assert len(out) == 3


def test_to_images_bad_format(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.to_images(sample, tmp_path / "x", fmt="xcf")


def test_from_images(tmp_path):
    from PIL import Image
    paths = []
    for i in range(3):
        p = tmp_path / f"i{i}.png"
        Image.new("RGB", (100, 80), (i * 80, 100, 200)).save(p)
        paths.append(p)
    out = pdf.from_images(paths, tmp_path / "out.pdf")
    assert pdf.info(out).page_count == 3


def test_roundtrip_pdf_to_images_to_pdf(tmp_path, sample):
    imgs = pdf.to_images(sample, tmp_path / "i", dpi=72)
    out = pdf.from_images(imgs, tmp_path / "back.pdf")
    assert pdf.info(out).page_count == 3


def test_to_text_file(tmp_path, sample):
    out = pdf.to_text_file(sample, tmp_path / "t.txt")
    assert "Page 1" in out.read_text()


# --- content --------------------------------------------------------------

def test_watermark_applies(tmp_path, sample):
    out = pdf.watermark(sample, tmp_path / "wm.pdf", text="CONFIDENTIAL")
    assert pdf.info(out).page_count == 3
    assert "CONFIDENTIAL" in pdf.extract_text(out)


def test_watermark_empty_text(tmp_path, sample):
    with pytest.raises(pdf.PdfError):
        pdf.watermark(sample, tmp_path / "w.pdf", text="")


def test_page_numbers(tmp_path, sample):
    out = pdf.add_page_numbers(sample, tmp_path / "n.pdf")
    assert pdf.info(out).page_count == 3


def test_set_metadata(tmp_path, sample):
    out = pdf.set_metadata(sample, tmp_path / "meta.pdf",
                           {"title": "My Title", "author": "Me"})
    meta = pdf.info(out).metadata
    assert meta.get("title") == "My Title"
    assert meta.get("author") == "Me"


# --- repair ---------------------------------------------------------------

@pytest.mark.skipif(not HAVE_QPDF, reason="needs qpdf")
def test_repair_valid_pdf(tmp_path, sample):
    out = pdf.repair(sample, tmp_path / "rep.pdf")
    assert pdf.info(out).page_count == 3


@pytest.mark.skipif(not HAVE_QPDF, reason="needs qpdf")
def test_repair_damaged_xref(tmp_path, sample):
    data = bytearray(sample.read_bytes())
    idx = data.rfind(b"startxref")
    if idx > 0:
        data[idx:idx + 9] = b"startxrXf"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(bytes(data))
    out = pdf.repair(broken, tmp_path / "fixed.pdf")
    assert pdf.info(out).page_count == 3


# --- OCR ------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_OCR, reason="needs ocrmypdf")
def test_ocr_adds_text_layer(tmp_path):
    """Render text to an image-only PDF, then OCR it back to searchable text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 200), "SEARCHABLE", fontsize=44)
    png = tmp_path / "scan.png"
    page.get_pixmap(dpi=200).save(str(png))
    doc.close()

    scan = tmp_path / "scan.pdf"
    pdf.from_images([png], scan)
    assert "SEARCHABLE" not in pdf.extract_text(scan)

    out = pdf.ocr(scan, tmp_path / "ocr.pdf", force=True)
    assert "SEARCHABLE" in pdf.extract_text(out).upper()
