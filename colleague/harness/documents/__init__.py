"""Seeded document synthesis: the corpora real work is made of.

The 2026-08-22 regime change: no task in the benchmark stays at toy scale.
A fixture that used to serve five rows from a seeded HTTP endpoint now
hands the arm what the person would actually hand a colleague — a batch of
multi-page PDFs and a large spreadsheet — and expects a produced file back.
This package is the machinery: renderers that turn a seeded source of
truth into invoices, statements, receipts, briefs and workbooks, a scan
layer that re-embeds a declared subset of pages as image-only distortions
(readable by vision, invisible to text extraction), and the reader the
scorers parse returned spreadsheets with.

Two disciplines carry over from the fixture servers unchanged:

**Determinism.** Every renderer is a pure function of its inputs. No wall
clock, no environment, no font files outside the PDF core set — the same
seed produces byte-identical files across processes, and `selftest`
regenerates a track's corpus twice to prove it. That is what keeps exact
recomputed ground truth possible at document scale.

**Ground truth never lives in the rendering.** The source-of-truth tables
stay in each track's fixture; expected outputs are recomputed from those
tables, never read back out of a generated document. A renderer that
drifted from its source would be caught by the scorer disagreeing with the
corpus, not hidden by both reading the same file.

These are the only modules in the harness allowed off the stdlib — the
deliberate trade recorded in pyproject.toml. The recording proxy and the
arm drivers stay stdlib-only so an arm can still be reproduced bare.
"""

from __future__ import annotations

try:
    import fpdf  # noqa: F401
    import openpyxl  # noqa: F401
    import PIL  # noqa: F401
    import pypdfium2  # noqa: F401
except ImportError as exc:  # pragma: no cover - environment, not logic
    raise ImportError(
        "the document-synthesis layer needs its rendering deps "
        "(fpdf2, openpyxl, pillow, pypdfium2) — run `uv sync`"
    ) from exc

from colleague.harness.documents.distort import (  # noqa: F401
    ScanSpec,
    page_texts,
    scan_pages,
)
from colleague.harness.documents.pdfgen import DocStyle, DocumentPdf  # noqa: F401
from colleague.harness.documents.xlsxio import (  # noqa: F401
    read_workbook,
    write_workbook,
)
