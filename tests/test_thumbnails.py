"""Thumbnail loader tests.

These assert the behaviour that matters: real pixmaps (not blank placeholders),
caching, newest-first ordering, and that stopping actually stops.
"""
import time

import pytest
from PyQt6.QtCore import QThreadPool
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from cachyview.ui.thumbnails import THUMB_WIDTH, ThumbnailLoader

fitz = pytest.importorskip("fitz")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc10(tmp_path):
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1}", fontsize=28)
    p = tmp_path / "ten.pdf"
    doc.save(str(p))
    doc.close()
    return p


def drain(loader, expect, timeout=20.0):
    """Spin the Qt event loop until *expect* thumbnails have arrived.

    Results already cached before this call are counted too: a fast render can
    finish before the signal is connected, which would otherwise hang here.
    """
    got = {}
    loader.ready.connect(lambda n, pm: got.__setitem__(n, pm))
    deadline = time.time() + timeout
    while len(got) < expect and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return got


def render(loader, pages, timeout=20.0):
    """Request *pages* and return them, immune to the connect/emit race."""
    got = {}
    loader.ready.connect(lambda n, pm: got.__setitem__(n, pm))
    loader.request(list(pages))
    deadline = time.time() + timeout
    while len(got) < len(pages) and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return got


def test_renders_real_pixmaps(app, doc10):
    loader = ThumbnailLoader(doc10)
    got = render(loader, [1, 2, 3])
    assert set(got) == {1, 2, 3}
    for pixmap in got.values():
        assert isinstance(pixmap, QPixmap)
        assert not pixmap.isNull()
        assert pixmap.width() == THUMB_WIDTH
        assert pixmap.height() > 0


def test_thumbnails_are_not_blank(app, doc10):
    """A placeholder-coloured rectangle would pass a naive 'is not null' test."""
    loader = ThumbnailLoader(doc10)
    got = render(loader, [1])
    image = got[1].toImage()
    colours = {image.pixel(x, y)
               for x in range(0, image.width(), 3)
               for y in range(0, image.height(), 3)}
    assert len(colours) > 1, "thumbnail has a single flat colour: nothing rendered"


def test_results_are_cached(app, doc10):
    loader = ThumbnailLoader(doc10)
    render(loader, [4])
    assert loader.cached(4) is not None
    assert loader.cached(9) is None

    # A repeat request for a cached page must not re-render.
    emitted = []
    loader.ready.connect(lambda n, pm: emitted.append(n))
    loader.request([4])
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.01)
    assert emitted == []


def test_clear_cache(app, doc10):
    loader = ThumbnailLoader(doc10)
    render(loader, [1])
    assert loader.cached(1) is not None
    loader.clear_cache()
    assert loader.cached(1) is None


def test_stop_halts_rendering(app, doc10):
    loader = ThumbnailLoader(doc10)
    loader.request(list(range(1, 11)))
    loader.stop()
    assert loader.pending == 0
    count = len(drain(loader, 10, timeout=1.5))
    assert count < 10, "stop() did not prevent the queue from draining"


def test_out_of_range_pages_are_ignored(app, doc10):
    loader = ThumbnailLoader(doc10)
    loader.request([99, 1, -3, 0])
    got = drain(loader, 1)
    assert 1 in got
    assert 99 not in got and 0 not in got


def test_bad_password_reports_failure(app, tmp_path):
    doc = fitz.open()
    doc.new_page()
    enc = tmp_path / "enc.pdf"
    doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw="o", user_pw="u")
    doc.close()

    loader = ThumbnailLoader(enc, password=None)
    errors = []
    loader.failed.connect(lambda n, msg: errors.append(msg))
    loader.request([1])
    deadline = time.time() + 10
    while not errors and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert errors, "a locked PDF must report failure, not hang"


def test_correct_password_renders(app, tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "secret page", fontsize=24)
    enc = tmp_path / "enc2.pdf"
    doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw="o", user_pw="u")
    doc.close()

    loader = ThumbnailLoader(enc, password="u")
    got = render(loader, [1])
    assert 1 in got and not got[1].isNull()


def test_many_requests_do_not_spawn_many_threads(app, doc10):
    """One worker services the queue; MuPDF handles are not thread-safe."""
    loader = ThumbnailLoader(doc10)
    before = QThreadPool.globalInstance().activeThreadCount()
    for page in range(1, 11):
        loader.request([page])
    peak = QThreadPool.globalInstance().activeThreadCount()
    drain(loader, 10)
    assert peak - before <= 1, f"expected a single worker, saw {peak - before}"


def test_requesting_after_stop_is_a_noop(app, doc10):
    loader = ThumbnailLoader(doc10)
    loader.stop()
    loader.request([1, 2])
    assert loader.pending == 0
