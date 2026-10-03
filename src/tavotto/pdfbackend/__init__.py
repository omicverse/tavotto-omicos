"""Stable PDF facade: only the preview backend is selectable in this round.

No call-site migration. Default behaviour is the original adapter. Opt in with
OMICOS_FIGURE_PREVIEW_BACKEND=pdfium in a reviewed environment. Other PDF/font/
export operations remain PyMuPDF; this is NOT complete removal or approval.
Selection is captured once at process start and included in the cache identity.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .contracts import CanvasProtocol
from .legacy_adapter import PymupdfBackend

_LEGACY = PymupdfBackend()
_SELECTED = os.environ.get("OMICOS_FIGURE_PREVIEW_BACKEND", "pymupdf")
if _SELECTED not in {"pymupdf", "pdfium"}:
    raise ValueError("Unknown OMICOS_FIGURE_PREVIEW_BACKEND; no fallback was selected")
try:
    _LEGACY_VERSION = version("pymupdf")
except PackageNotFoundError:
    _LEGACY_VERSION = "unavailable"
if _SELECTED == "pdfium":
    from .preview_pdfium import PdfiumPreview

    _PREVIEW = PdfiumPreview()
    BACKEND_NAME = "pymupdf-with-pdfium-preview"
    BACKEND_VERSION = f"{_LEGACY_VERSION};{_PREVIEW.backend_version}"
else:
    _PREVIEW = _LEGACY
    BACKEND_NAME = "pymupdf"
    BACKEND_VERSION = _LEGACY_VERSION


# Defer the legacy native import for a preview-only process with the PDFium option.
def __getattr__(name: str):
    if name in {"CANVAS_TEXT_FAMILIES", "COVERAGE_MAX_CP"}:
        return getattr(_LEGACY.module, name)
    raise AttributeError(name)


def annotate_asset(
    pdf_path: Path, png_path: Path | None, objects: list[dict], dpi: int = 600
) -> None:
    return _LEGACY.annotate_asset(pdf_path, png_path, objects, dpi)


def compare_png(baseline: Path, candidate: Path) -> dict:
    return _LEGACY.compare_png(baseline, candidate)


def compose(page_w_mm: float, page_h_mm: float, transparent: bool = False) -> CanvasProtocol:
    return _LEGACY.compose(page_w_mm, page_h_mm, transparent)


def coverage_ranges() -> dict:
    return _LEGACY.coverage_ranges()


def hex2rgb(s: str) -> tuple[float, float, float]:
    return _LEGACY.hex2rgb(s)


def missing_glyphs(
    s: str, family: object = "serif", bold: bool = False, italic: bool = False
) -> list[str]:
    return _LEGACY.missing_glyphs(s, family, bold, italic)


def mm2pt(mm: float) -> float:
    return _LEGACY.mm2pt(mm)


def original_pdf(src: Path, out: Path, page_pt: tuple[float, float] | None = None) -> dict:
    return _LEGACY.original_pdf(src, out, page_pt)


def original_png(src: Path, out: Path, ppi: int | None, transparent: bool = False) -> dict:
    return _LEGACY.original_png(src, out, ppi, transparent)


def original_tiff(
    src: Path,
    out: Path,
    ppi: int | None,
    transparent: bool = False,
    *,
    dpi_meta: float | None = None,
) -> dict:
    return _LEGACY.original_tiff(src, out, ppi, transparent, dpi_meta=dpi_meta)


def pdf_fonts(path: Path) -> list[str]:
    return _LEGACY.pdf_fonts(path)


def probe_asset(path: Path, kind: str) -> dict:
    return _LEGACY.probe_asset(path, kind)


def render_preview_png(path: Path, width_px: int, out: Path) -> None:
    return _PREVIEW.render_preview_png(path, width_px, out)


def text_plan(
    s: str, family: object = "serif", bold: bool = False, italic: bool = False
) -> list[tuple[str, str]]:
    return _LEGACY.text_plan(s, family, bold, italic)


def text_width(
    s: str, size_pt: float, bold: bool = False, italic: bool = False, family: object = "serif"
) -> float:
    return _LEGACY.text_width(s, size_pt, bold, italic, family)


__all__ = [
    "BACKEND_NAME",
    "BACKEND_VERSION",
    "CANVAS_TEXT_FAMILIES",
    "COVERAGE_MAX_CP",
    "annotate_asset",
    "compare_png",
    "compose",
    "coverage_ranges",
    "hex2rgb",
    "missing_glyphs",
    "mm2pt",
    "original_pdf",
    "original_png",
    "original_tiff",
    "pdf_fonts",
    "probe_asset",
    "render_preview_png",
    "text_plan",
    "text_width",
]
