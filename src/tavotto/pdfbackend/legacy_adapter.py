"""The legacy implementation remains byte-for-byte unchanged behind this adapter."""

from __future__ import annotations

from functools import cached_property
from importlib import import_module
from pathlib import Path

from .contracts import CanvasProtocol


class PymupdfBackend:
    @cached_property
    def module(self):
        return import_module(".pymupdf_backend", __package__)

    def annotate_asset(
        self, pdf_path: Path, png_path: Path | None, objects: list[dict], dpi: int = 600
    ) -> None:
        return self.module.annotate_asset(pdf_path, png_path, objects, dpi)

    def compare_png(self, baseline: Path, candidate: Path) -> dict:
        return self.module.compare_png(baseline, candidate)

    def compose(
        self, page_w_mm: float, page_h_mm: float, transparent: bool = False
    ) -> CanvasProtocol:
        return self.module.compose(page_w_mm, page_h_mm, transparent)

    def coverage_ranges(self) -> dict:
        return self.module.coverage_ranges()

    def hex2rgb(self, s: str) -> tuple[float, float, float]:
        return self.module.hex2rgb(s)

    def missing_glyphs(
        self, s: str, family: object = "serif", bold: bool = False, italic: bool = False
    ) -> list[str]:
        return self.module.missing_glyphs(s, family, bold, italic)

    def mm2pt(self, mm: float) -> float:
        return self.module.mm2pt(mm)

    def original_pdf(
        self, src: Path, out: Path, page_pt: tuple[float, float] | None = None
    ) -> dict:
        return self.module.original_pdf(src, out, page_pt)

    def original_png(
        self, src: Path, out: Path, ppi: int | None, transparent: bool = False
    ) -> dict:
        return self.module.original_png(src, out, ppi, transparent)

    def original_tiff(
        self,
        src: Path,
        out: Path,
        ppi: int | None,
        transparent: bool = False,
        *,
        dpi_meta: float | None = None,
    ) -> dict:
        return self.module.original_tiff(src, out, ppi, transparent, dpi_meta=dpi_meta)

    def pdf_fonts(self, path: Path) -> list[str]:
        return self.module.pdf_fonts(path)

    def probe_asset(self, path: Path, kind: str) -> dict:
        return self.module.probe_asset(path, kind)

    def render_preview_png(self, path: Path, width_px: int, out: Path) -> None:
        return self.module.render_preview_png(path, width_px, out)

    def text_plan(
        self, s: str, family: object = "serif", bold: bool = False, italic: bool = False
    ) -> list[tuple[str, str]]:
        return self.module.text_plan(s, family, bold, italic)

    def text_width(
        self,
        s: str,
        size_pt: float,
        bold: bool = False,
        italic: bool = False,
        family: object = "serif",
    ) -> float:
        return self.module.text_width(s, size_pt, bold, italic, family)
