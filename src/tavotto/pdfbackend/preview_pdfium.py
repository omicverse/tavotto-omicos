"""Fixed-width first-page PDF preview using PDFium, not PyMuPDF.

Only this adapter calls PDFium. It serializes native calls and owns/explicitly
closes every handle. It does not execute source scripts, replace vector export,
load form JavaScript or silently fall back to another renderer. Resource limits
are input/pixel limits, NOT a hostile-PDF sandbox or a bound on native CPU time.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import tempfile
import threading
from pathlib import Path

_PDFIUM_LOCK = threading.RLock()
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_WIDTH = 8192
MAX_PIXELS = 32_000_000


class PreviewError(RuntimeError):
    """Stable machine code; the original exception remains available via __cause__."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PdfiumPreview:
    backend_name = "pdfium-preview"

    @property
    def backend_version(self) -> str:
        with _PDFIUM_LOCK:
            import pypdfium2 as pdfium

            return f"pypdfium2={pdfium.PYPDFIUM_INFO};pdfium={pdfium.PDFIUM_INFO}"

    def render_preview_png(self, path: Path, width_px: int, out: Path) -> None:
        if type(width_px) is not int or not 1 <= width_px <= MAX_WIDTH:
            raise PreviewError(
                "PREVIEW_WIDTH_LIMIT", f"Preview width must be an integer from 1 to {MAX_WIDTH}"
            )
        path, out = Path(path), Path(out)
        if path.resolve() == out.resolve():
            raise PreviewError(
                "PREVIEW_OUTPUT_IS_INPUT", "Preview output must not replace the PDF input"
            )
        if not path.is_file():
            raise PreviewError("PREVIEW_INPUT_INVALID", "Preview requires a regular PDF file")
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno())
            if not stat.S_ISREG(size.st_mode) or size.st_size > MAX_INPUT_BYTES:
                raise PreviewError(
                    "PREVIEW_INPUT_LIMIT", "Preview PDF exceeds the input limit or is not regular"
                )
            content = stream.read(MAX_INPUT_BYTES + 1)
        if len(content) > MAX_INPUT_BYTES:
            raise PreviewError("PREVIEW_INPUT_LIMIT", "Preview PDF grew beyond the input limit")
        # The parsed bytes are immutable for this request, even if the source is concurrently edited.
        image = None
        with _PDFIUM_LOCK:
            import pypdfium2 as pdfium

            document = page = bitmap = view = None
            try:
                document = pdfium.PdfDocument(content)
                if len(document) < 1:
                    raise PreviewError("PREVIEW_EMPTY_PDF", "PDF has no pages")
                if document.get_formtype() != 0:
                    raise PreviewError(
                        "PREVIEW_FORMS_UNSUPPORTED",
                        "Interactive PDF forms are not supported by this preview adapter",
                    )
                page = document[0]
                w, h = page.get_size()
                if not all(math.isfinite(v) and v > 0 for v in (w, h)):
                    raise PreviewError(
                        "PREVIEW_GEOMETRY_INVALID", "PDF page geometry is not finite and positive"
                    )
                # PDFium exposes page dimensions as binary32. A mathematically
                # integral height can become 609.000022 and ceil to 610. Define
                # our fixed-width raster grid before allocation (0.001 pixel
                # near-integer tolerance); never resize/crop a rendered image.
                exact_height = h * width_px / w
                nearest = round(exact_height)
                height = nearest if abs(exact_height - nearest) < 0.001 else math.ceil(exact_height)
                if height < 1:
                    raise PreviewError(
                        "PREVIEW_GEOMETRY_INVALID", "Preview height rounds below one pixel"
                    )
                scale = min(width_px / w, height / h)
                if math.ceil(w * scale) > width_px or math.ceil(h * scale) > height:
                    scale = math.nextafter(scale, 0.0)
                if width_px * height > MAX_PIXELS:
                    raise PreviewError(
                        "PREVIEW_PIXEL_LIMIT", "Preview page exceeds the pixel budget"
                    )
                bitmap = page.render(
                    scale=scale,
                    fill_color=(255, 255, 255, 255),
                    draw_annots=True,
                    may_draw_forms=False,
                    rev_byteorder=True,
                )
                view = bitmap.to_pil()
                image = view.convert("RGB")  # independent copy, no native buffer escapes the lock
                if image.width != width_px or image.height != height:
                    raise PreviewError(
                        "PREVIEW_PIXEL_GRID",
                        f"Renderer produced {image.size}, expected {(width_px, height)}; no resampling performed",
                    )
            except PreviewError:
                if image is not None:
                    image.close()
                raise
            except Exception as exc:
                if image is not None:
                    image.close()
                raise PreviewError("PREVIEW_RENDER_FAILED", f"PDF preview failed: {exc}") from exc
            finally:
                if view is not None:
                    view.close()
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
                if document is not None:
                    document.close()
        if image is None:
            raise PreviewError("PREVIEW_RENDER_FAILED", "Renderer returned no image")
        temporary: str | None = None
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix="." + out.name + "-", suffix=".png", dir=out.parent
            )
            with os.fdopen(fd, "wb") as stream:
                image.save(stream, format="PNG")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, out)
            temporary = None
        finally:
            image.close()
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


def native_evidence() -> dict:
    """Report exact installed runtime identity; this is not a distribution approval."""
    import importlib.metadata as metadata

    distribution = metadata.distribution("pypdfium2")
    artifacts = []
    for item in distribution.files or []:
        name = str(item)
        if name.endswith((".so", ".dll", ".dylib")) or "/licenses/" in name:
            p = Path(distribution.locate_file(item))
            if p.is_file():
                artifacts.append(
                    {
                        "path": name,
                        "bytes": p.stat().st_size,
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                )
    return {
        "wrapper_version": distribution.version,
        "backend_version": PdfiumPreview().backend_version,
        "platform": __import__("sys").platform,
        "artifacts": artifacts,
        "distribution_approved": False,
    }
