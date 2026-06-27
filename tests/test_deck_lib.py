"""Tests for deck_lib pure helpers. The Deck class (python-pptx) is exercised only when
python-pptx is installed; otherwise that test is skipped."""
from __future__ import annotations

import importlib.util

import pytest

import deck_lib


# --------------------------------------------------------------------------- hex_to_rgb
def test_hex_to_rgb_with_and_without_hash():
    assert deck_lib.hex_to_rgb("2E5AAC") == (46, 90, 172)
    assert deck_lib.hex_to_rgb("#FFFFFF") == (255, 255, 255)


@pytest.mark.parametrize("bad", ["12345", "GGGGGG", "", "#abc", "12 34 56"])
def test_hex_to_rgb_rejects_invalid(bad):
    with pytest.raises(ValueError):
        deck_lib.hex_to_rgb(bad)


# --------------------------------------------------------------------------- image_fit
def test_image_fit_preserves_aspect_and_fits_box():
    # 2000x1000 (2:1) into a 800x800 box -> width-bound: 800x400, aspect preserved.
    w, h = deck_lib.image_fit(2000, 1000, 800, 800)
    assert (round(w), round(h)) == (800, 400)
    assert abs((w / h) - 2.0) < 1e-9
    assert w <= 800 + 1e-9 and h <= 800 + 1e-9


def test_image_fit_height_bound():
    # 1000x2000 (1:2) into 800x800 -> height-bound: 400x800.
    w, h = deck_lib.image_fit(1000, 2000, 800, 800)
    assert (round(w), round(h)) == (400, 800)


def test_image_fit_does_not_upscale_beyond_box():
    w, h = deck_lib.image_fit(100, 100, 50, 50)
    assert w <= 50 + 1e-9 and h <= 50 + 1e-9


@pytest.mark.parametrize("args", [(0, 100, 10, 10), (100, 0, 10, 10), (-1, 5, 10, 10)])
def test_image_fit_rejects_nonpositive(args):
    with pytest.raises(ValueError):
        deck_lib.image_fit(*args)


# --------------------------------------------------------------------------- fit_text
def test_fit_text_truncates_with_ellipsis():
    out = deck_lib.fit_text("this is a fairly long headline", 12)
    assert out.endswith("…") and len(out) <= 12


def test_fit_text_noop_when_short():
    assert deck_lib.fit_text("short", 20) == "short"


def test_fit_text_collapses_whitespace():
    assert deck_lib.fit_text("a   b\tc", 20) == "a b c"


# --------------------------------------------------------------------------- PALETTE sanity
def test_palette_values_are_valid_hex():
    for key, val in deck_lib.PALETTE.items():
        deck_lib.hex_to_rgb(val)  # raises if any palette color is malformed


# --------------------------------------------------------------------------- Deck (needs python-pptx)
@pytest.mark.skipif(importlib.util.find_spec("pptx") is None, reason="python-pptx not installed")
def test_deck_builds_and_saves(tmp_path):
    d = deck_lib.Deck("T", footer="f")
    d.title_slide("T", "sub")
    d.section_divider("Sec")
    s = d.content_slide("An assertion headline", ["a", "b"])
    d.notes(s, "talk track")
    d.stat_tiles("Numbers", [("3x", "faster"), ("0", "steps")])
    d.closing_slide("Thanks", "x@y.z")
    out = d.save(str(tmp_path / "o.pptx"))
    assert out.endswith("o.pptx")
    assert (tmp_path / "o.pptx").stat().st_size > 0
    assert len(d.prs.slides._sldIdLst) == 5
