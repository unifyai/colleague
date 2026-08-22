"""A deterministic multi-page PDF builder over fpdf2.

fpdf2 is already reproducible if three leaks are plugged: the creation
timestamp (pinned here, derived from nothing), font files (core fonts
only — helvetica, times, courier — which live inside every PDF reader
rather than in the output), and any wall-clock or randomness in the
caller. `DocumentPdf` plugs the first two and exposes just enough layout
vocabulary — headings, paragraphs, tables, key-value blocks, page
footers — for a fixture to compose realistic invoices, statements,
receipts and briefs without hand-placing coordinates.

Layout *variety* is data, not chance: a `DocStyle` bundles the visual
decisions one issuer would make (typeface, margins, table rule weight,
header treatment), and a fixture derives each vendor's style from its
seed. Two vendors look like two different back offices; the same vendor
looks the same every week; and everything is still a pure function of the
seed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from fpdf import FPDF

#: One fixed timestamp for every generated document. Corpora are synthetic
#: evidence, not records of when a benchmark ran; a real timestamp would
#: break byte-determinism for nothing.
CREATION_DATE = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)

#: The PDF core faces. Nothing outside this tuple may be requested: core
#: fonts embed no font program, so the bytes stay identical everywhere.
FACES = ("helvetica", "times", "courier")


@dataclass(frozen=True)
class DocStyle:
    """The visual identity of one document issuer, derived from a seed."""

    face: str = "helvetica"
    base_size: float = 9.5
    heading_size: float = 15.0
    margin_mm: float = 16.0
    table_rule: float = 0.2
    """Table border line width in mm; 0 draws no rules at all."""

    shaded_header: bool = True
    """Whether table header rows carry a light grey fill."""

    @staticmethod
    def derive(h: int) -> "DocStyle":
        """A style from a 64-bit hash — `stable_hash` output, typically."""
        return DocStyle(
            face=FACES[h % len(FACES)],
            base_size=9.0 + (h >> 3) % 3 * 0.5,
            heading_size=14.0 + (h >> 5) % 3,
            margin_mm=14.0 + (h >> 7) % 3 * 2,
            table_rule=(0.2 if (h >> 9) % 3 else 0.0),
            shaded_header=bool((h >> 11) % 2),
        )


class DocumentPdf:
    """One A4 document under construction."""

    def __init__(self, style: DocStyle | None = None) -> None:
        self.style = style or DocStyle()
        self.pdf = FPDF(unit="mm", format="A4")
        self.pdf.creation_date = CREATION_DATE
        m = self.style.margin_mm
        self.pdf.set_margins(m, m, m)
        self.pdf.set_auto_page_break(True, margin=m)
        self._page_footer: str | None = None

    @property
    def width(self) -> float:
        return self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def page(self) -> "DocumentPdf":
        self.pdf.add_page()
        return self

    def heading(self, text: str, *, size: float | None = None) -> "DocumentPdf":
        self.pdf.set_font(self.style.face, "B", size or self.style.heading_size)
        # multi_cell parks the cursor at the right edge by default; every
        # helper pins it back to the left margin so the next write always
        # has the full line.
        self.pdf.multi_cell(
            0,
            (size or self.style.heading_size) * 0.55,
            text,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.pdf.ln(2)
        return self

    def subheading(self, text: str) -> "DocumentPdf":
        self.pdf.set_font(self.style.face, "B", self.style.base_size + 1.5)
        self.pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(1)
        return self

    def para(self, text: str, *, size: float | None = None) -> "DocumentPdf":
        self.pdf.set_font(self.style.face, "", size or self.style.base_size)
        self.pdf.multi_cell(
            0,
            (size or self.style.base_size) * 0.5,
            text,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.pdf.ln(1.5)
        return self

    def kv(self, pairs: Iterable[tuple[str, str]]) -> "DocumentPdf":
        """A label/value block — the letterhead corner of an invoice."""
        label_w = self.width * 0.3
        for label, value in pairs:
            self.pdf.set_font(self.style.face, "B", self.style.base_size)
            self.pdf.cell(label_w, 5.5, label)
            self.pdf.set_font(self.style.face, "", self.style.base_size)
            self.pdf.multi_cell(0, 5.5, value, new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(1.5)
        return self

    def gap(self, mm: float = 4.0) -> "DocumentPdf":
        self.pdf.ln(mm)
        return self

    def table(
        self,
        headers: list[str],
        rows: list[list[Any]],
        *,
        widths: list[float] | None = None,
        align: list[str] | None = None,
    ) -> "DocumentPdf":
        """A ruled table that breaks across pages, headers repeated.

        ``widths`` are fractions of the printable width and must sum to 1;
        ``align`` is per-column ``"L"``/``"R"``/``"C"``.
        """
        n = len(headers)
        fr = widths or [1.0 / n] * n
        al = align or ["L"] * n
        w = [self.width * f for f in fr]
        border = 1 if self.style.table_rule else 0
        self.pdf.set_line_width(self.style.table_rule or 0.2)

        def header_row() -> None:
            self.pdf.set_font(self.style.face, "B", self.style.base_size)
            fill = self.style.shaded_header
            if fill:
                self.pdf.set_fill_color(228)
            for i, h in enumerate(headers):
                self.pdf.cell(w[i], 6.5, h, border=border, align=al[i], fill=fill)
            self.pdf.ln()

        header_row()
        self.pdf.set_font(self.style.face, "", self.style.base_size)
        row_h = 6.0
        for row in rows:
            if self.pdf.get_y() + row_h > self.pdf.h - self.pdf.b_margin:
                self.pdf.add_page()
                header_row()
                self.pdf.set_font(self.style.face, "", self.style.base_size)
            for i, cell in enumerate(row):
                text = cell if isinstance(cell, str) else str(cell)
                # One line per cell: overlong text is clipped, not wrapped,
                # so a row is always one band and page breaks stay simple.
                self.pdf.cell(w[i], row_h, text, border=border, align=al[i])
            self.pdf.ln()
        self.pdf.ln(2)
        return self

    def rule(self) -> "DocumentPdf":
        y = self.pdf.get_y()
        self.pdf.set_line_width(0.3)
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(2)
        return self

    def bytes(self) -> bytes:
        return bytes(self.pdf.output())

    def save(self, path) -> None:
        data = self.bytes()
        with open(path, "wb") as f:
            f.write(data)


def image_only_pdf(pages_jpeg: list[bytes]) -> bytes:
    """An A4 PDF whose every page is one full-bleed JPEG and nothing else.

    The scan layer uses this to re-embed distorted pages: no text layer
    exists, so extraction returns nothing and the content is reachable
    only by looking.
    """
    pdf = FPDF(unit="mm", format="A4")
    pdf.creation_date = CREATION_DATE
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    for jpeg in pages_jpeg:
        pdf.add_page()
        pdf.image(io.BytesIO(jpeg), x=0, y=0, w=210, h=297)
    return bytes(pdf.output())
