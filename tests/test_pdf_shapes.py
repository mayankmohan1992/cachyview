"""Shape annotation backend tests (markup expansion: Preview-like drawing)."""
import fitz
import pytest
from pathlib import Path

from cachyview.backends import pdf as pb


@pytest.fixture
def doc(tmp_path):
    d = fitz.open()
    d.new_page(width=400, height=500)
    p = tmp_path / "doc.pdf"
    d.save(p)
    d.close()
    return p


def test_write_and_read_all_shape_kinds(doc):
    out = doc.with_name("out.pdf")
    pb.add_annotations(doc, out, [
        pb.Annotation(page=1, kind="rectangle", rect=(10, 20, 300, 400),
                      color=(1.0, 0, 0)),
        pb.Annotation(page=1, kind="oval", rect=(20, 30, 200, 300),
                      color=(0, 0, 1)),
        pb.Annotation(page=1, kind="arrow", rect=(10, 10, 200, 200),
                      points=[(10, 10), (200, 200)], color=(0, 1, 0)),
        pb.Annotation(page=1, kind="line", rect=(10, 400, 300, 400),
                      points=[(10, 400), (300, 400)], color=(0.5, 0.5, 0.5)),
        pb.Annotation(page=1, kind="strike", rect=(50, 440, 350, 450),
                      color=(0.2, 0.2, 0.2)),
        pb.Annotation(page=1, kind="sketch", rect=(10, 10, 100, 100),
                      points=[(10, 10), (50, 80), (100, 10)], color=(1, 0, 1)),
    ])
    anns = {a.kind: a for a in pb.list_annotations(out)}
    assert set(anns) == {"rectangle", "oval", "arrow", "line", "strike", "sketch"}
    assert anns["arrow"].points == [(10.0, 10.0), (200.0, 200.0)]
    assert anns["line"].points == [(10.0, 400.0), (300.0, 400.0)]
    assert anns["sketch"].points == [(10.0, 10.0), (50.0, 80.0), (100.0, 10.0)]


def test_arrow_round_trips_through_pdf(doc):
    # A /Line annotation with an end-arrow must read back as "arrow".
    out = doc.with_name("out.pdf")
    pb.add_annotations(out if False else doc, out,
                      [pb.Annotation(page=1, kind="arrow",
                                     rect=(0, 0, 100, 100),
                                     points=[(0, 0), (100, 100)])])
    kinds = [a.kind for a in pb.list_annotations(out)]
    assert "arrow" in kinds
