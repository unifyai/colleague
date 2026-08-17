"""Render a screen as pixels, with nothing but the standard library.

The `screenshare` track needs the arm to *see* what somebody did — frames of
their screen, not a text description of it — and the harness is stdlib-only
so a third party can reproduce a run forever. So this is a bitmap font, a
framebuffer and a PNG encoder, enough to draw a small application window
legibly at a few times the glyph size.

Everything is uppercase and monospaced. That is a deliberate floor: if a
vision model cannot read a 15×21 px block-capital, it cannot follow a screen
share, and the track should say so rather than paper over it with prettier
type it could not have rendered without a dependency.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# 5x7 glyphs, one string per row, '#' lit. Lowercase maps to uppercase.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "B": ("#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "),
    "C": (" ####", "#    ", "#    ", "#    ", "#    ", "#    ", " ####"),
    "D": ("#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "),
    "E": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    "F": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "),
    "G": (" ####", "#    ", "#    ", "#  ##", "#   #", "#   #", " ####"),
    "H": ("#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "I": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"),
    "J": ("  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "),
    "K": ("#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "P": ("#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "),
    "Q": (" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"),
    "R": ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    "S": (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "V": ("#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "),
    "W": ("#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"),
    "X": ("#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"),
    "Y": ("#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "),
    "Z": ("#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"),
    "0": (" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "),
    "1": ("  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "2": (" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"),
    "3": ("#####", "   # ", "  #  ", "   # ", "    #", "#   #", " ### "),
    "4": ("   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "),
    "5": ("#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "),
    "6": ("  ## ", " #   ", "#    ", "#### ", "#   #", "#   #", " ### "),
    "7": ("#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "),
    "8": (" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "),
    "9": (" ### ", "#   #", "#   #", " ####", "    #", "   # ", " ##  "),
    " ": ("     ",) * 7,
    ".": ("     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "),
    ",": ("     ", "     ", "     ", "     ", " ##  ", "  #  ", " #   "),
    ":": ("     ", " ##  ", " ##  ", "     ", " ##  ", " ##  ", "     "),
    "-": ("     ", "     ", "     ", "#####", "     ", "     ", "     "),
    "_": ("     ", "     ", "     ", "     ", "     ", "     ", "#####"),
    "/": ("    #", "    #", "   # ", "  #  ", " #   ", "#    ", "#    "),
    "(": ("   # ", "  #  ", " #   ", " #   ", " #   ", "  #  ", "   # "),
    ")": (" #   ", "  #  ", "   # ", "   # ", "   # ", "  #  ", " #   "),
    "[": (" ### ", " #   ", " #   ", " #   ", " #   ", " #   ", " ### "),
    "]": (" ### ", "   # ", "   # ", "   # ", "   # ", "   # ", " ### "),
    "#": (" # # ", " # # ", "#####", " # # ", "#####", " # # ", " # # "),
    "'": ("  #  ", "  #  ", "     ", "     ", "     ", "     ", "     "),
    "!": ("  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "),
    "?": (" ### ", "#   #", "    #", "   # ", "  #  ", "     ", "  #  "),
    ">": ("#    ", " #   ", "  #  ", "   # ", "  #  ", " #   ", "#    "),
    "<": ("    #", "   # ", "  #  ", " #   ", "  #  ", "   # ", "    #"),
    "=": ("     ", "     ", "#####", "     ", "#####", "     ", "     "),
    "+": ("     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "),
    "*": ("     ", "# # #", " ### ", "#####", " ### ", "# # #", "     "),
    "|": ("  #  ",) * 7,
    "@": (" ### ", "#   #", "# ###", "# # #", "# ###", "#    ", " ### "),
}
_UNKNOWN = ("#####", "#   #", "#   #", "#   #", "#   #", "#   #", "#####")

GLYPH_W, GLYPH_H = 5, 7

Color = tuple[int, int, int]
WHITE: Color = (255, 255, 255)
BLACK: Color = (20, 20, 20)
GREY: Color = (120, 120, 120)
LIGHT: Color = (232, 232, 232)
BLUE: Color = (30, 90, 200)
GREEN: Color = (30, 140, 70)
RED: Color = (190, 40, 40)
AMBER: Color = (200, 130, 20)


class Canvas:
    """An RGB framebuffer with just enough drawing to fake a small window."""

    def __init__(self, width: int, height: int, background: Color = WHITE) -> None:
        self.width = width
        self.height = height
        self._px = bytearray(bytes(background) * (width * height))

    def rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            start = (yy * self.width + x0) * 3
            self._px[start : start + len(row)] = row

    def text(self, x: int, y: int, s: str, color: Color = BLACK, scale: int = 3) -> int:
        """Draw ``s`` with its top-left at (x, y); returns the x after it."""
        cx = x
        for ch in s.upper():
            rows = _GLYPHS.get(ch, _UNKNOWN)
            for ry, row in enumerate(rows):
                for rx, lit in enumerate(row):
                    if lit == "#":
                        self.rect(cx + rx * scale, y + ry * scale, scale, scale, color)
            cx += (GLYPH_W + 1) * scale
        return cx

    def png(self) -> bytes:
        raw = bytearray()
        stride = self.width * 3
        for yy in range(self.height):
            raw.append(0)  # filter: none
            raw += self._px[yy * stride : (yy + 1) * stride]

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        return b"".join(
            [
                b"\x89PNG\r\n\x1a\n",
                chunk(
                    b"IHDR",
                    struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0),
                ),
                chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
                chunk(b"IEND", b""),
            ],
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png())
        return path
