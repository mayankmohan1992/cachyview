"""GUI tests for the archive, image and PDF tabs, driving real widgets."""
import subprocess
import zipfile

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from cachyview.ui.archive_tab import ArchiveTab, human_size
from cachyview.ui.image_tab import ImageTab, pil_to_qpixmap
from cachyview.ui.main_window import MainWindow

fitz = pytest.importorskip("fitz")
from cachyview.ui.pdf_tab import PdfTab  # noqa: E402




@pytest.fixture
def zip_file(tmp_path):
    src = tmp_path / "stuff"
    (src / "docs").mkdir(parents=True)
    (src / "readme.txt").write_text("hello from the archive\n")
    (src / "docs" / "notes.txt").write_text("nested note\n")
    out = tmp_path / "bundle.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(src / "readme.txt", "readme.txt")
        zf.write(src / "docs" / "notes.txt", "docs/notes.txt")
    return out


@pytest.fixture
def png_file(tmp_path):
    p = tmp_path / "pic.png"
    img = Image.new("RGB", (120, 80))
    for x in range(120):
        for y in range(80):
            img.putpixel((x, y), (x * 2 % 256, y * 3 % 256, 90))
    img.save(p)
    return p


@pytest.fixture
def pdf_file(tmp_path):
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 120), f"Document page {i + 1}", fontsize=20)
    p = tmp_path / "doc.pdf"
    doc.save(str(p))
    doc.close()
    return p


# --- helpers --------------------------------------------------------------

@pytest.mark.parametrize("size,want", [
    (0, "0 B"), (512, "512 B"), (1024, "1.0 KB"),
    (1536, "1.5 KB"), (1048576, "1.0 MB"),
])
def test_human_size(size, want):
    assert human_size(size) == want


# --- archive tab ----------------------------------------------------------

def test_archive_tab_lists_entries(app, pump, zip_file):
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    assert tab.info is not None
    assert tab.info.file_count == 2
    assert tab.tree.topLevelItemCount() >= 1
    assert "2 files" in tab.status.text()


def test_archive_tab_builds_folder_tree(app, pump, zip_file):
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    labels = [tab.tree.topLevelItem(i).text(0)
              for i in range(tab.tree.topLevelItemCount())]
    assert "docs" in labels
    assert "readme.txt" in labels


def test_archive_filter_hides_rows(app, pump, zip_file):
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    tab.filter.setText("readme")
    visible = [tab.tree.topLevelItem(i).text(0)
               for i in range(tab.tree.topLevelItemCount())
               if not tab.tree.topLevelItem(i).isHidden()]
    assert "readme.txt" in visible
    tab.filter.setText("")
    assert not tab.tree.topLevelItem(0).isHidden()


def test_archive_flat_view_uses_full_paths(app, pump, zip_file):
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    tab.flat.setChecked(True)
    labels = [tab.tree.topLevelItem(i).text(0)
              for i in range(tab.tree.topLevelItemCount())]
    assert "docs/notes.txt" in labels
    assert "docs" not in labels, "flat view must not show folders"


def test_archive_double_click_extracts_and_emits(app, pump, zip_file, qtbot=None):
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    emitted = []
    tab.open_request.connect(emitted.append)

    item = None
    for i in range(tab.tree.topLevelItemCount()):
        candidate = tab.tree.topLevelItem(i)
        if candidate.text(0) == "readme.txt":
            item = candidate
    assert item is not None
    tab._on_double_click(item, 0)

    assert emitted, "double click should emit the extracted path"
    from pathlib import Path
    assert Path(emitted[0]).read_text() == "hello from the archive\n"
    tab.cleanup()


def test_archive_sandbox_purged_on_cleanup(app, pump, zip_file):
    tab = ArchiveTab(zip_file)
    sandbox = tab._sandbox.path
    assert sandbox.exists()
    tab.cleanup()
    assert not sandbox.exists()


def test_archive_tab_integrity_ok(app, pump, zip_file, monkeypatch):
    shown = {}
    monkeypatch.setattr(
        "cachyview.ui.archive_tab.QMessageBox.information",
        lambda *a, **k: shown.update(text=a[2]))
    tab = ArchiveTab(zip_file)
    pump(lambda: not tab.is_listing)
    tab.test_integrity()
    assert "intact" in shown.get("text", "")


def test_encrypted_archive_does_not_block(app, pump, tmp_path):
    """Opening an encrypted archive must not pop a modal dialog.

    Regression: the constructor called QInputDialog, which hangs forever when
    no user is present (headless runs, service-menu invocations).
    """
    if subprocess.run(["which", "7z"], capture_output=True).returncode != 0:
        pytest.skip("needs 7zip")
    src = tmp_path / "secret.txt"
    src.write_text("classified\n")
    enc = tmp_path / "locked.zip"
    subprocess.run(["7z", "a", "-tzip", "-pletmein", "-bso0", "-bsp0",
                    "--", str(enc), str(src)], check=True, capture_output=True)

    # A zip keeps filenames readable, so listing succeeds and the tab must
    # flag the lock rather than block on a dialog.
    tab = ArchiveTab(enc)          # must return promptly
    pump(lambda: not tab.is_listing)
    assert tab.info is not None and tab.info.encrypted
    assert "encrypted" in tab.status.text()

    # Extraction without the password must fail as "password required",
    # not as "wrong password".
    from cachyview.backends import archive as ar
    with pytest.raises(ar.PasswordRequired):
        ar.extract(enc, tmp_path / "nopw")

    tab.password = "letmein"
    tab.reload(prompt=False)
    pump(lambda: not tab.is_listing)
    assert tab.info is not None and tab.info.file_count == 1
    assert "unlocked" in tab.status.text()


def test_broken_archive_reports_error(app, pump, tmp_path):
    bad = tmp_path / "notreally.zip"
    bad.write_bytes(b"PK\x03\x04" + b"\xff" * 200)
    tab = ArchiveTab(bad)
    pump(lambda: not tab.is_listing)
    assert tab.error or tab.info is not None


# --- image tab ------------------------------------------------------------

def test_pil_to_qpixmap(png_file):
    from cachyview.backends import image as ib
    pm = pil_to_qpixmap(ib.load(png_file))
    assert pm.width() == 120 and pm.height() == 80
    assert not pm.isNull()


def test_image_tab_loads(app, png_file):
    tab = ImageTab(png_file)
    assert tab.current.size == (120, 80)
    assert "120×80" in tab.status.text()
    assert not tab.is_modified()


def test_image_tab_rotate_updates_preview(app, png_file):
    tab = ImageTab(png_file)
    tab.add_op("rotate", angle=90)
    assert tab.current.size == (80, 120)
    assert tab.is_modified()
    assert "1 edit" in tab.status.text()


def test_image_tab_undo_redo(app, png_file):
    tab = ImageTab(png_file)
    tab.add_op("rotate", angle=90)
    tab.add_op("invert")
    assert len(tab.ops) == 2
    tab.undo()
    assert len(tab.ops) == 1 and tab.current.size == (80, 120)
    tab.undo()
    assert not tab.ops and tab.current.size == (120, 80)
    assert not tab.is_modified()
    tab.redo()
    assert len(tab.ops) == 1 and tab.current.size == (80, 120)


def test_image_tab_undo_past_start_is_safe(app, png_file):
    tab = ImageTab(png_file)
    for _ in range(5):
        tab.undo()
    assert tab.current.size == (120, 80)


def test_new_op_clears_redo(app, png_file):
    tab = ImageTab(png_file)
    tab.add_op("rotate", angle=90)
    tab.undo()
    tab.add_op("invert")
    assert not tab._redo


def test_image_tab_save_writes_file(app, png_file):
    tab = ImageTab(png_file)
    tab.add_op("scale", factor=0.5)
    assert tab.save()
    from cachyview.backends import image as ib
    assert ib.info(png_file).width == 60
    assert not tab.is_modified()


def test_image_zoom_controls(app, png_file):
    tab = ImageTab(png_file)
    tab.canvas.actual_size()
    assert tab.canvas.zoom == 1.0
    tab.canvas.zoom_in()
    assert tab.canvas.zoom > 1.0
    tab.canvas.zoom_out()
    assert tab.canvas.zoom == pytest.approx(1.0)


def test_image_zoom_clamped(app, png_file):
    tab = ImageTab(png_file)
    for _ in range(30):
        tab.canvas.zoom_in()
    assert tab.canvas.zoom <= 32.0
    for _ in range(60):
        tab.canvas.zoom_out()
    assert tab.canvas.zoom >= 0.01


# --- pdf tab --------------------------------------------------------------

def test_pdf_tab_loads(app, pdf_file):
    tab = PdfTab(pdf_file)
    assert tab.info is not None
    assert tab.info.page_count == 4
    assert tab.page == 1
    assert "Page 1 of 4" in tab.status.text()


def test_pdf_tab_navigation(app, pdf_file):
    tab = PdfTab(pdf_file)
    tab.next_page()
    assert tab.page == 2
    tab.prev_page()
    assert tab.page == 1
    tab.prev_page()
    assert tab.page == 1          # clamped at the first page
    tab.go_to(99)
    assert tab.page == 4          # clamped at the last page


def test_pdf_tab_page_box(app, pdf_file):
    tab = PdfTab(pdf_file)
    tab.page_box.setText("3")
    tab._on_page_box()
    assert tab.page == 3
    tab.page_box.setText("not a number")
    tab._on_page_box()
    assert tab.page == 3          # invalid input is reverted


def test_pdf_tab_renders_pixmap(app, pdf_file):
    tab = PdfTab(pdf_file)
    pixmap = tab.page_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_pdf_tab_thumbnails_listed(app, pdf_file):
    tab = PdfTab(pdf_file)
    assert tab.thumbs.count() == 4


def test_pdf_tab_search_finds_page(app, pdf_file):
    tab = PdfTab(pdf_file)
    tab.search_box.setText("page 3")
    tab.search_next()
    assert tab.page == 3
    assert "Found" in tab.status.text()


def test_pdf_tab_search_missing_text(app, pdf_file):
    tab = PdfTab(pdf_file)
    tab.search_box.setText("zzz-not-here")
    tab.search_next()
    assert "not found" in tab.status.text()


def test_pdf_tab_zoom(app, pdf_file):
    tab = PdfTab(pdf_file)
    start = tab.zoom
    tab.zoom_in()
    assert tab.zoom > start
    tab.zoom_out()
    assert tab.zoom == pytest.approx(start)


def test_pdf_page_cache_is_bounded(app, pdf_file):
    tab = PdfTab(pdf_file)
    for _ in range(3):
        for n in range(1, 5):
            tab.go_to(n)
            tab.zoom_in()
    assert len(tab._page_cache) <= 25


# --- routing through the main window --------------------------------------

def test_main_window_routes_each_kind(app, tmp_path, zip_file, png_file, pdf_file):
    win = MainWindow()
    txt = tmp_path / "notes.txt"
    txt.write_text("plain text\n")

    win.open_path(txt)
    win.open_path(zip_file)
    win.open_path(png_file)
    win.open_path(pdf_file)
    assert win.tabs.count() == 4

    from cachyview.ui.text_tab import TextTab
    kinds = [type(win.tabs.widget(i)).__name__ for i in range(4)]
    assert kinds == ["TextTab", "ArchiveTab", "ImageTab", "PdfTab"]
    assert isinstance(win.tabs.widget(0), TextTab)

    while win.tabs.count():
        win.close_tab(0)


def test_pdf_output_path_does_not_clobber(tmp_path):
    from cachyview.ui.pdf_tools import output_path
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-1.7\n")
    first = output_path(src, "compressed")
    assert first.name == "report-compressed.pdf"
    first.write_bytes(b"x")
    second = output_path(src, "compressed")
    assert second.name == "report-compressed-2.pdf"
