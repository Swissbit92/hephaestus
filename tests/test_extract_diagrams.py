"""Tests for extract_diagrams pure helpers. The render path (PyMuPDF + Pillow) runs only
when those libs are installed; otherwise it's skipped."""
from __future__ import annotations

import importlib.util

import pytest

import extract_diagrams as ed


# --------------------------------------------------------------------------- scaled_size
def test_scaled_size_caps_long_edge_preserving_aspect():
    # 4000x1000 (4:1), cap 2000 -> 2000x500
    assert ed.scaled_size(4000, 1000, 2000) == (2000, 500)


def test_scaled_size_height_dominant():
    assert ed.scaled_size(1000, 4000, 2000) == (500, 2000)


def test_scaled_size_no_upscale():
    assert ed.scaled_size(800, 600, 2000) == (800, 600)


@pytest.mark.parametrize("args", [(0, 10, 100), (10, 0, 100), (-5, 10, 100)])
def test_scaled_size_rejects_nonpositive(args):
    with pytest.raises(ValueError):
        ed.scaled_size(*args)


# --------------------------------------------------------------------------- parse_pages
def test_parse_pages_none_returns_all():
    assert ed.parse_pages(None, 3) == [0, 1, 2]


def test_parse_pages_converts_1based_and_dedups_and_filters():
    assert ed.parse_pages("1,3,5,3,99", 4) == [0, 2]  # 5->idx4 out of range(4); dup 3 dropped


def test_parse_pages_empty_spec():
    assert ed.parse_pages("", 2) == [0, 1]


# --------------------------------------------------------------------------- output_name
def test_output_name_default_padded():
    assert ed.output_name("report", 0) == "report-p01.png"
    assert ed.output_name("report", 9) == "report-p10.png"


def test_output_name_semantic_when_provided():
    assert ed.output_name("report", 0, ["Intro Diagram"]) == "intro-diagram.png"


def test_output_name_falls_back_when_name_blank_or_missing():
    assert ed.output_name("r", 1, ["only-first"]) == "r-p02.png"  # no name for page idx 1
    assert ed.output_name("r", 0, ["  "]) == "r-p01.png"          # blank name


# --------------------------------------------------------------------------- dpi_zoom
def test_dpi_zoom():
    assert ed.dpi_zoom(72) == 1.0
    assert ed.dpi_zoom(300) == pytest.approx(300 / 72)


def test_dpi_zoom_rejects_nonpositive():
    with pytest.raises(ValueError):
        ed.dpi_zoom(0)


# --------------------------------------------------------------------------- render (needs fitz+PIL)
@pytest.mark.skipif(
    importlib.util.find_spec("fitz") is None or importlib.util.find_spec("PIL") is None,
    reason="PyMuPDF/Pillow not installed",
)
def test_extract_renders_png(tmp_path):
    import fitz

    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello figure")
    doc.save(str(pdf))
    doc.close()

    out = ed.extract(pdf, tmp_path / "figs", dpi=150, max_edge=1000)
    assert len(out) == 1
    assert out[0].endswith("doc-p01.png")
    assert (tmp_path / "figs" / "doc-p01.png").stat().st_size > 0
