"""Extract figures from a PDF as slide-ready PNGs — companion to deck_lib.

Renders each page (or a subset) at a target DPI, trims surrounding whitespace, flattens
transparency to white, and caps the long edge so files stay light enough for Google Slides
import. Heavy deps (PyMuPDF `fitz`, Pillow) are imported lazily inside `extract`, so the
pure helpers below import and unit-test with no third-party dependency.

CLI:
    python3 extract_diagrams.py <file.pdf> --out figs/ [--pages 1,3,5] [--dpi 300]
            [--max-edge 2000] [--names intro,arch,results] [--no-trim]

Requires (only to actually render): `pip install pymupdf pillow`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DPI = 300
DEFAULT_MAX_EDGE = 2000  # px on the long edge — keeps PNGs ~<2MB for Slides import


# --- Pure helpers (no third-party import) ------------------------------------


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    Windows consoles default to a legacy codepage (commonly cp1252), so a single em-dash
    or check-mark in otherwise successful output raises UnicodeEncodeError *after* the
    work is done — turning a passing gate into exit 1, which reads as a real failure.
    Reconfiguring is a no-op on platforms that are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # a detached or captured stream (pytest); nothing to reconfigure


def scaled_size(w: int, h: int, max_edge: int = DEFAULT_MAX_EDGE) -> tuple[int, int]:
    """Cap the long edge at max_edge, preserving aspect ratio. Never upscales."""
    if w <= 0 or h <= 0:
        raise ValueError("image dimensions must be positive")
    longest = max(w, h)
    if longest <= max_edge:
        return w, h
    scale = max_edge / longest
    return max(1, round(w * scale)), max(1, round(h * scale))


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'1,3,5' (1-based) -> [0,2,4] (0-based), filtered to the valid range. None -> all."""
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        idx = int(part) - 1
        if 0 <= idx < total and idx not in out:
            out.append(idx)
    return out


def output_name(pdf_stem: str, page_index: int, names: list[str] | None = None) -> str:
    """Semantic name if provided for this page, else `<stem>-p<NN>.png`."""
    if names and page_index < len(names) and names[page_index].strip():
        safe = "-".join(names[page_index].strip().lower().split())
        return f"{safe}.png"
    return f"{pdf_stem}-p{page_index + 1:02d}.png"


def dpi_zoom(dpi: int) -> float:
    """PDF points are 72/inch; the render zoom factor for a target DPI."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    return dpi / 72.0


# --- Rendering (lazy fitz + Pillow) ------------------------------------------
def extract(
    pdf_path: str | Path,
    out_dir: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    max_edge: int = DEFAULT_MAX_EDGE,
    pages: str | None = None,
    names: list[str] | None = None,
    trim: bool = True,
) -> list[str]:
    """Render selected pages to PNGs in out_dir. Returns the written paths."""
    import fitz  # PyMuPDF
    from PIL import Image

    pdf_path = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    doc = fitz.open(str(pdf_path))
    try:
        page_indices = parse_pages(pages, doc.page_count)
        zoom = dpi_zoom(dpi)
        written: list[str] = []
        for pi in page_indices:
            page = doc.load_page(pi)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if trim:
                img = _trim_whitespace(img)
            w, h = scaled_size(img.width, img.height, max_edge)
            if (w, h) != (img.width, img.height):
                img = img.resize((w, h), Image.LANCZOS)
            dest = out / output_name(stem, pi, names)
            img.save(str(dest), "PNG")
            written.append(str(dest))
        return written
    finally:
        doc.close()


def _trim_whitespace(img, bg=(255, 255, 255), tol: int = 8):
    """Crop near-uniform background margins; flatten any alpha to white first."""
    from PIL import Image, ImageChops

    if img.mode != "RGB":
        img = img.convert("RGB")
    background = Image.new("RGB", img.size, bg)
    diff = ImageChops.difference(img, background)
    bbox = diff.getbbox()  # None if the whole image is background
    if bbox:
        # Pad by a couple px so glyphs aren't shaved.
        left, top, right, bottom = bbox
        left = max(0, left - 2); top = max(0, top - 2)
        right = min(img.width, right + 2); bottom = min(img.height, bottom + 2)
        return img.crop((left, top, right, bottom))
    return img


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Extract PDF pages as slide-ready PNGs")
    ap.add_argument("pdf")
    ap.add_argument("--out", default="figures", help="output directory")
    ap.add_argument("--pages", help="1-based page list, e.g. 1,3,5 (default: all)")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--max-edge", type=int, default=DEFAULT_MAX_EDGE)
    ap.add_argument("--names", help="comma-separated semantic names, one per selected page")
    ap.add_argument("--no-trim", action="store_true", help="do not trim whitespace margins")
    args = ap.parse_args(argv)

    names = [n for n in args.names.split(",")] if args.names else None
    try:
        written = extract(args.pdf, args.out, dpi=args.dpi, max_edge=args.max_edge,
                          pages=args.pages, names=names, trim=not args.no_trim)
    except ModuleNotFoundError as e:
        sys.stderr.write(f"error: missing dependency ({e.name}). Install: pip install pymupdf pillow\n")
        return 1
    for p in written:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main(sys.argv[1:]))
