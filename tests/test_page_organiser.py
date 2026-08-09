"""Page organiser tests: the grid model and the layout it produces."""
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from cachyview.backends import pdf as pb
from cachyview.ui.page_organiser import ROTATION_ROLE, SOURCE_ROLE, PageOrganiser

fitz = pytest.importorskip("fitz")
pytest.importorskip("pikepdf")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc5(tmp_path):
    doc = fitz.open()
    for i in range(5):
        page = doc.new_page()
        page.insert_text((72, 100), f"PAGE {i + 1}", fontsize=30)
    p = tmp_path / "five.pdf"
    doc.save(str(p))
    doc.close()
    return p


@pytest.fixture
def org(app, doc5):
    dialog = PageOrganiser(doc5)
    yield dialog
    dialog.cleanup()


def select(dialog, rows):
    dialog.grid.clearSelection()
    for row in rows:
        item = dialog.grid.item(row)
        assert item is not None
        item.setSelected(True)


# --- population -----------------------------------------------------------

def test_grid_has_one_item_per_page(org):
    assert org.page_count == 5
    assert org.grid.count() == 5
    for row in range(5):
        assert org.grid.item(row).data(SOURCE_ROLE) == row + 1


def test_initial_plan_is_identity(org):
    assert org.layout_plan() == [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]
    assert org.is_unchanged()


def test_thumbnails_arrive(org):
    deadline = time.time() + 15
    while org._loader.cached(1) is None and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert org._loader.cached(1) is not None


# --- editing --------------------------------------------------------------

def test_rotate_selected(org):
    select(org, [0, 2])
    org._rotate(90)
    plan = org.layout_plan()
    assert plan[0] == (1, 90)
    assert plan[2] == (3, 90)
    assert plan[1] == (2, 0)
    assert not org.is_unchanged()


def test_rotate_accumulates_and_wraps(org):
    select(org, [0])
    for _ in range(4):
        org._rotate(90)
    assert org.layout_plan()[0] == (1, 0), "four right turns is a full circle"


def test_rotate_left_normalises_to_positive(org):
    select(org, [0])
    org._rotate(-90)
    assert org.layout_plan()[0] == (1, 270)


def test_delete_removes_rows(org):
    select(org, [1, 3])
    org._delete()
    assert org.grid.count() == 3
    assert [s for s, _ in org.layout_plan()] == [1, 3, 5]


def test_delete_refuses_to_empty_the_document(org, monkeypatch):
    warned = []
    monkeypatch.setattr("cachyview.ui.page_organiser.QMessageBox.warning",
                        lambda *a, **k: warned.append(a))
    org.grid.selectAll()
    org._delete()
    assert org.grid.count() == 5, "must not delete every page"
    assert warned


def test_duplicate_inserts_after_original(org):
    select(org, [0])
    org._duplicate()
    assert org.grid.count() == 6
    assert [s for s, _ in org.layout_plan()] == [1, 1, 2, 3, 4, 5]


def test_duplicate_carries_rotation(org):
    select(org, [0])
    org._rotate(90)
    select(org, [0])
    org._duplicate()
    plan = org.layout_plan()
    assert plan[0] == (1, 90) and plan[1] == (1, 90)


def test_duplicate_then_rotate_one_copy_only(org):
    select(org, [0])
    org._duplicate()
    select(org, [1])
    org._rotate(180)
    plan = org.layout_plan()
    assert plan[0] == (1, 0)
    assert plan[1] == (1, 180), "rotating a copy must not affect the original"


def test_reset_restores_original(org):
    select(org, [0])
    org._rotate(90)
    org._delete()
    org._reset()
    assert org.grid.count() == 5
    assert org.is_unchanged()


def test_buttons_without_selection_do_not_crash(org, monkeypatch):
    monkeypatch.setattr("cachyview.ui.page_organiser.QMessageBox.information",
                        lambda *a, **k: None)
    org.grid.clearSelection()
    org._rotate(90)
    org._duplicate()
    org._delete()
    assert org.grid.count() == 5
    assert org.is_unchanged()


def test_labels_show_new_position_and_source(org):
    select(org, [0])
    org._delete()
    first = org.grid.item(0)
    assert first.text().startswith("1")
    assert "was 2" in first.text()


# --- applying the plan ----------------------------------------------------

def test_apply_layout_matches_the_grid(org, tmp_path, doc5):
    select(org, [1])
    org._delete()          # drop page 2
    select(org, [0])
    org._duplicate()       # duplicate page 1
    select(org, [1])
    org._rotate(90)

    plan = org.layout_plan()
    assert [s for s, _ in plan] == [1, 1, 3, 4, 5]

    out = tmp_path / "organised.pdf"
    pb.apply_layout(doc5, out, plan)

    info = pb.info(out)
    assert info.page_count == 5
    assert [p.rotation for p in info.pages] == [0, 90, 0, 0, 0]
    texts = [pb.extract_text(out, [n]).strip() for n in range(1, 6)]
    assert texts == ["PAGE 1", "PAGE 1", "PAGE 3", "PAGE 4", "PAGE 5"]


def test_reordering_the_model_changes_the_plan(org, tmp_path, doc5):
    """Simulate a drag: move the last row to the front."""
    item = org.grid.takeItem(4)
    org.grid.insertItem(0, item)
    org._renumber()
    assert [s for s, _ in org.layout_plan()] == [5, 1, 2, 3, 4]

    out = tmp_path / "moved.pdf"
    pb.apply_layout(doc5, out, org.layout_plan())
    assert pb.extract_text(out, [1]).strip() == "PAGE 5"


def test_organiser_on_locked_pdf_warns(app, tmp_path, monkeypatch):
    doc = fitz.open()
    doc.new_page()
    enc = tmp_path / "locked.pdf"
    doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw="o", user_pw="u")
    doc.close()

    warned = []
    monkeypatch.setattr("cachyview.ui.page_organiser.QMessageBox.warning",
                        lambda *a, **k: warned.append(a))
    dialog = PageOrganiser(enc)          # no password given
    assert warned, "a locked document must warn, not raise"
    assert dialog.grid.count() == 0
    dialog.cleanup()


def test_drag_drop_is_enabled(org):
    from PyQt6.QtWidgets import QAbstractItemView
    assert org.grid.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
    assert org.grid.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


def test_overwrite_original_replaces_the_file(app, doc5, monkeypatch):
    # Accept the confirmation and capture the write callback's output.
    yes = __import__("PyQt6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox
    monkeypatch.setattr("cachyview.ui.page_organiser.QMessageBox.question",
                        lambda *a, **k: yes.StandardButton.Yes)

    written: dict[str, object] = {}
    import cachyview.core.safe as safe_mod
    real_replace = safe_mod.replace_in_place

    def fake_replace(dest, write):
        written["dest"] = dest
        out = real_replace(dest, write)
        written["result"] = out
        return out

    monkeypatch.setattr(safe_mod, "replace_in_place", fake_replace)

    dialog = PageOrganiser(doc5)
    dialog._overwrite()
    dialog.cleanup()

    assert written["dest"] == doc5, "must target the original path"
    assert written["result"] == doc5
    # apply_layout actually rewrote the file: reopen proves it parses.
    import fitz as _fitz
    reopened = _fitz.open(doc5)
    assert reopened.page_count == 5
    reopened.close()

