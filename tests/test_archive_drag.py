"""Archive drag-out tests."""
import pytest
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTreeWidgetItem, QWidget

from cachyview.backends import archive as ar
from cachyview.core.sandbox import Sandbox
from cachyview.ui.archive_drag import DraggableArchiveTree


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def archive(tmp_path):
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("beta")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("gamma")
    zip_path = tmp_path / "bundle.zip"
    ar.create(zip_path, [tmp_path / "a.txt", tmp_path / "b.txt",
                         tmp_path / "sub" / "c.txt"])
    return zip_path


def build_tree(archive, sandbox, host=None):
    tree = DraggableArchiveTree(host)
    tree.path = archive
    tree.password = None
    tree._sandbox = sandbox
    for e in ar.list_archive(archive).entries:
        it = QTreeWidgetItem([e.name])
        it.setData(0, Qt.ItemDataRole.UserRole, e.name if not e.is_dir else None)
        tree.addTopLevelItem(it)
    tree.setSelectionMode(tree.SelectionMode.ExtendedSelection)
    return tree


def test_no_selection_offers_nothing(archive, app):
    with Sandbox(prefix="drag-") as sb:
        tree = build_tree(archive, sb)
        assert tree._selected_file_members() == []


def test_selected_members_return_names(archive, app):
    with Sandbox(prefix="drag-") as sb:
        tree = build_tree(archive, sb)
        tree.topLevelItem(0).setSelected(True)
        assert tree._selected_file_members() == ["a.txt"]


def test_drag_offers_real_extracted_files(archive, app, monkeypatch):
    captured = {}

    class FakeDrag:
        def __init__(self, source):
            self._mime = None
        def setMimeData(self, mime):
            captured["mime"] = mime
        def exec(self, actions):
            captured["executed"] = True
            return 1

    monkeypatch.setattr("cachyview.ui.archive_drag.QDrag", FakeDrag)

    with Sandbox(prefix="drag-") as sb:
        tree = build_tree(archive, sb)
        tree.topLevelItem(0).setSelected(True)   # a.txt
        tree.topLevelItem(1).setSelected(True)   # b.txt

        tree.startDrag(Qt.DropAction.CopyAction)

        assert captured.get("executed")
        urls = captured["mime"].urls()
        names = sorted(u.toLocalFile().rsplit("/", 1)[-1] for u in urls)
        assert names == ["a.txt", "b.txt"]
        for u in urls:
            assert Path(u.toLocalFile()).exists()


def test_drag_failure_is_reported_to_host(archive, app, monkeypatch):
    failures = []
    monkeypatch.setattr(
        "cachyview.ui.archive_drag.ar.extract",
        lambda *a, **k: (_ for _ in ()).throw(ar.ArchiveError("boom")))

    with Sandbox(prefix="drag3-") as sb:
        host = QWidget()
        tree = build_tree(archive, sb, host)
        host._drag_failed = lambda m: failures.append(m)
        tree.topLevelItem(0).setSelected(True)
        tree.startDrag(Qt.DropAction.CopyAction)
        assert failures == ["boom"]
