"""The scan layer: pages that must be *looked at*, not extracted.

A benchmark can claim its tasks need vision only if text extraction
genuinely returns nothing for the load-bearing content. This module makes
that true by construction: a declared, seeded subset of a document's pages
is rasterised, distorted the way a phone-scanned receipt is distorted —
slight rotation, sensor noise, softness, tired contrast — and re-embedded
as image-only pages. The distortion is calibrated to what an office scan
actually looks like: legible to a person and to a vision model, hostile
only to `pdftotext`. Punishing vision with an unreadable page would fail
arms for the fixture's sin.

Everything is seeded. The same seed produces the same rotation, the same
noise bytes, the same JPEG — `selftest` holds the corpus to
byte-determinism, and `page_texts` is how it proves a distorted page
carries no text layer at all.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter

from colleague.harness.documents.pdfgen import image_only_pdf


@dataclass(frozen=True)
class ScanSpec:
    """How hard the scanner was having a day. Defaults are a fair office scan."""

    dpi: float = 150.0
    max_rotate_deg: float = 2.0
    noise: float = 0.07
    """Blend weight of the uniform-noise layer; 0 disables it."""

    blur: float = 0.5
    contrast: float = 0.85
    jpeg_quality: int = 65


def _scan_one(page_img: Image.Image, rng: random.Random, spec: ScanSpec) -> bytes:
    g = page_img.convert("L")
    if spec.max_rotate_deg:
        angle = rng.uniform(-spec.max_rotate_deg, spec.max_rotate_deg)
        g = g.rotate(angle, expand=False, fillcolor=235, resample=Image.BICUBIC)
    if spec.noise:
        noise = Image.frombytes("L", g.size, rng.randbytes(g.size[0] * g.size[1]))
        g = Image.blend(g, noise, spec.noise)
    if spec.blur:
        g = g.filter(ImageFilter.GaussianBlur(radius=spec.blur))
    if spec.contrast != 1.0:
        g = ImageEnhance.Contrast(g).enhance(spec.contrast)
    buf = io.BytesIO()
    g.save(buf, "JPEG", quality=spec.jpeg_quality)
    return buf.getvalue()


def scan_pages(
    pdf_bytes: bytes,
    pages: list[int] | None = None,
    *,
    seed: int,
    spec: ScanSpec = ScanSpec(),
) -> bytes:
    """Re-render ``pages`` (0-based; None means all) as image-only scans.

    Returns a whole replacement PDF: undistorted pages pass through as
    they were, distorted pages become full-bleed JPEGs with no text layer.
    """
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        chosen = set(range(len(doc))) if pages is None else set(pages)
        out_of_range = [p for p in chosen if not 0 <= p < len(doc)]
        if out_of_range:
            raise ValueError(f"pages out of range: {sorted(out_of_range)}")
        if not chosen:
            return pdf_bytes

        scale = spec.dpi / 72.0
        scans: dict[int, bytes] = {}
        for index in sorted(chosen):
            # One rng per page, keyed by page index: dropping a page from
            # the distorted set never changes another page's bytes.
            rng = random.Random((seed << 16) ^ index)
            img = doc[index].render(scale=scale).to_pil()
            scans[index] = _scan_one(img, rng, spec)

        replacement = pdfium.PdfDocument(image_only_pdf(list(scans.values())))
        try:
            merged = pdfium.PdfDocument.new()
            scan_pos = {p: i for i, p in enumerate(sorted(chosen))}
            for index in range(len(doc)):
                if index in scan_pos:
                    merged.import_pages(
                        replacement, pages=[scan_pos[index]], index=len(merged)
                    )
                else:
                    merged.import_pages(doc, pages=[index], index=len(merged))
            buf = io.BytesIO()
            merged.save(buf)
            merged.close()
            return _pin_document_id(buf.getvalue(), seed)
        finally:
            replacement.close()
    finally:
        doc.close()


_TRAILER_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]{32}>\s*<[0-9A-Fa-f]{32}>\s*\]")
_PDF_DATE = re.compile(rb"/(CreationDate|ModDate)\s*\(([^)]*)\)")


def _pin_document_id(pdf_bytes: bytes, seed: int) -> bytes:
    """Replace pdfium's time-derived bytes with seed-derived ones.

    A pdfium save is deterministic except for the two 32-hex document IDs
    in the trailer and the Info dictionary's creation/modification dates.
    Every replacement is the same length as what it replaces (dates pad
    with spaces inside the string literal, which PDF permits), so every
    xref offset stays valid.
    """
    pinned = hashlib.sha256(f"colleague-scan:{seed}".encode()).hexdigest()[:32]
    fixed_id = f"/ID[<{pinned.upper()}><{pinned.upper()}>]".encode()

    def swap_id(match: re.Match[bytes]) -> bytes:
        return fixed_id if len(fixed_id) == len(match.group(0)) else match.group(0)

    def swap_date(match: re.Match[bytes]) -> bytes:
        room = len(match.group(2))
        stamp = b"D:20260105090000+00'00'"[:room].ljust(room, b" ")
        return b"/" + match.group(1) + b"(" + stamp + b")"

    return _PDF_DATE.sub(swap_date, _TRAILER_ID.sub(swap_id, pdf_bytes))


def page_texts(pdf_bytes: bytes) -> list[str]:
    """Extractable text per page — what a text-only pipeline would see.

    The selftest guarantee reads: for every distorted page this is empty,
    and for every content marker the fixture declares vision-critical, no
    page's text contains it.
    """
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        out = []
        for page in doc:
            textpage = page.get_textpage()
            out.append(textpage.get_text_bounded())
            textpage.close()
        return out
    finally:
        doc.close()
