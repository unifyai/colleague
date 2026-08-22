"""The document layer is deterministic, and its scans are truly image-only.

Every guarantee the document-scale regime leans on is pinned here at the
unit level: the same inputs render byte-identical PDFs and workbooks (the
precondition for exact recomputed ground truth), the scan layer strips the
text layer from exactly the pages it was told to and no others, and the
workbook reader hands back cell values exactly as typed — string amounts
stay strings, because that distinction is scored.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fpdf")

from colleague.harness.attachments import attachment_note, find_deliverable
from colleague.harness.documents import (
    DocStyle,
    DocumentPdf,
    ScanSpec,
    page_texts,
    read_workbook,
    scan_pages,
    write_workbook,
)


def _sample_pdf(pages: int = 3) -> bytes:
    doc = DocumentPdf(DocStyle.derive(7))
    for i in range(pages):
        doc.page().heading(f"Statement page {i + 1}").para(
            f"MARKER-PAGE-{i + 1} some ordinary body text for page {i + 1}."
        ).table(
            ["ref", "vendor", "amount"],
            [[f"R-{i}-{j}", "Atelier Nord", f"{j}.00"] for j in range(10)],
            widths=[0.3, 0.4, 0.3],
            align=["L", "L", "R"],
        )
    return doc.bytes()


def test_pdf_generation_is_byte_deterministic():
    assert _sample_pdf() == _sample_pdf()


def test_pdf_pages_carry_their_text():
    texts = page_texts(_sample_pdf())
    assert len(texts) == 3
    for i, text in enumerate(texts):
        assert f"MARKER-PAGE-{i + 1}" in text


def test_scan_strips_text_from_exactly_the_declared_pages():
    scanned = scan_pages(_sample_pdf(), [1], seed=42)
    texts = page_texts(scanned)
    assert len(texts) == 3
    assert "MARKER-PAGE-1" in texts[0]
    assert texts[1].strip() == ""
    assert "MARKER-PAGE-3" in texts[2]


def test_scan_is_byte_deterministic_and_seed_sensitive():
    a = scan_pages(_sample_pdf(), [0, 2], seed=42)
    b = scan_pages(_sample_pdf(), [0, 2], seed=42)
    c = scan_pages(_sample_pdf(), [0, 2], seed=43)
    assert a == b
    assert a != c


def test_scan_rejects_out_of_range_pages():
    with pytest.raises(ValueError):
        scan_pages(_sample_pdf(), [99], seed=1)


def test_workbook_roundtrip_preserves_cell_types(tmp_path):
    path = tmp_path / "report.xlsx"
    rows = [
        ["Northwind Client Spend - Week 2"],
        ["vendor", "category", "amount_eur", "flagged"],
        ["Cobalt Cloud", "software", "812.40", False],
        ["Atelier Nord", "supplies", "13.07", True],
    ]
    write_workbook(path, {"report": rows})
    back = read_workbook(path)["report"]
    assert back[0][0] == "Northwind Client Spend - Week 2"
    assert back[2][2] == "812.40" and isinstance(back[2][2], str)
    assert back[3][3] is True
    # None-padding differences between what was written and what a sparse
    # sheet stores are the reader's business to keep out of the scorer.
    assert [r[: len(rows[i])] for i, r in enumerate(back)] == rows


def test_workbook_writing_is_byte_deterministic(tmp_path):
    rows = {"data": [[i, f"row {i}", i / 7] for i in range(500)]}
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    write_workbook(a, rows)
    write_workbook(b, rows)
    assert a.read_bytes() == b.read_bytes()


def test_unparseable_bytes_raise_for_the_scorer_to_catch():
    with pytest.raises(Exception):
        read_workbook(b"this is not a workbook")


def test_attachment_note_is_stable_and_minimal():
    note = attachment_note(["/w/inbox/statement.pdf", "/w/inbox/rates.xlsx"])
    assert "/w/inbox/statement.pdf" in note and "/w/inbox/rates.xlsx" in note
    assert attachment_note([]) == ""


def test_find_deliverable_prefers_the_named_path(tmp_path):
    (tmp_path / "old.xlsx").write_bytes(b"old")
    named = tmp_path / "out" / "report_week_2.xlsx"
    named.parent.mkdir()
    named.write_bytes(b"new")
    hit, how = find_deliverable(f"Done - saved to out/report_week_2.xlsx.", [tmp_path])
    assert hit == named.resolve()
    assert how == "named_in_reply"


def test_find_deliverable_falls_back_to_newest_and_skips_inputs(tmp_path):
    inbox = tmp_path / "inbox" / "rates.xlsx"
    inbox.parent.mkdir()
    inbox.write_bytes(b"input")
    produced = tmp_path / "report.xlsx"
    produced.write_bytes(b"output")
    hit, how = find_deliverable(
        "All done.", [tmp_path], ignore=lambda p: p == inbox.resolve()
    )
    assert hit == produced.resolve()
    assert how == "discovered_in_workspace"
    hit, how = find_deliverable("All done.", [tmp_path], ignore=lambda p: True)
    assert hit is None and how == ""
