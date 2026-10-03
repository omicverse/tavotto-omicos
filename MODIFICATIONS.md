# Statement of modifications (AGPL-3.0 §5a)

This work is a **modified version** of Tavotto.

- **Base:** `Tavotto/Tavotto` commit `eb1404942ad60a776403fd4a9d3c85459bc5a8b0`
  (upstream release 0.15.0).
- **Modified by:** OmicOS (OmicVerse).
- **Date of these modifications:** 2026-09-27 (published), developed 2026-09.
- **Runtime version string:** `0.15.1` (strict SemVer for Codex plugin validation; it is not an
  upstream release).
- **Licence:** unchanged, AGPL-3.0-only.

The complete diff is this repository's history on top of the base commit. In summary,
the modifications:

1. **Remove upstream visual brand assets and product marks** and substitute OmicOS
   presentation (mark, theme, window/panel chrome, localized copy). Protocol and
   package identifiers are deliberately unchanged for compatibility.
2. **Integrate the OmicOS assistant**: the workbench's AI panel talks to the host
   application's model gateway instead of carrying its own provider configuration
   (run / history / revert / cancel semantics retained).
3. **Bind projects to OmicOS workspace paths** and migrate legacy export directory
   names, keeping read-only and network projects usable.
4. **Add a PDF backend facade** (`src/tavotto/pdfbackend/`): the original
   implementation and all its callers are unchanged; an optional PDFium-based
   first-page preview backend is selectable with
   `OMICOS_FIGURE_PREVIEW_BACKEND=pdfium`, and the `pdfium-preview` extra pins
   `pypdfium2`/`Pillow`.
5. **Add an import-scope module** (`src/tavotto/engine/importscope.py`) and route
   figure capture through it, so a project's own namespace is honoured when
   historical probes are concatenated.
6. **Fix and stabilize** asset recency ordering, asset deletion controls, raster
   preview stability, export feedback/visual issues, workbench layout compaction,
   the AI reasoning picker, AI render refresh, and structured figure error surfaces
   (`web/src/components/FigureError.tsx` and friends).
7. **Record build provenance** in `src/tavotto/_omicos_build.json` (channel, base
   commit, source digest, runtime version).
8. **Publish the engine on its own** as the `omicos-figure-engine` distribution
   (`scripts/build_engine_package.py`): exactly the worker's import closure from
   `src/tavotto/engine/`, staged as the package `omicos_figure_engine`, depending on
   matplotlib and numpy only (no Flask, no PyMuPDF, no web assets). OmicOS drives it
   over wire protocol v1 in the user's own interpreter. Alongside: `ping` now reports
   the engine identity and interpreter versions, `preview_png` reports override
   warnings like `render`/`export` do (both additive, protocol version unchanged),
   and the OmicVerse `marker_heatmap` shim is installed by a post-import hook only
   after a script imports `omicverse.pl`, instead of importing OmicVerse eagerly on
   every build.

## Identity of a built artifact

This tree is the source channel OmicOS builds the runtime from. A built artifact
records its own identity in `src/tavotto/_omicos_build.json` (channel, base commit,
source digest, runtime version); that marker, not this README, is what the host
application verifies before running it. Generated raster assets are regenerated
during the build and are sensitive to the exact matplotlib/Pillow/libwebp versions,
so a rebuild on a different toolchain can produce a different source digest while
the code is identical — use `BUILD.md`'s pins if you want to match.

No upstream copyright notice, licence text or contributor history has been removed.
