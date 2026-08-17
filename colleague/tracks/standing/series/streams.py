"""Seeded, released, seq-keyed streams — the world most fire-series fixtures serve.

A stream is a deterministic sequence of rows keyed by an integer ``seq``.
The harness *releases* rows before a fire; a reader pages through them with
``?after=N``; the sink the automation writes to is its own cursor. Ground
truth for any seq range is recomputed from the generator, so a transform the
harness applies to what the API *shows* (a rename, a unit change, a smaller
page) never touches what is *true*.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from colleague.harness.fixture_server import stable_hash

RowGenerator = Callable[[int, int], dict[str, Any]]
RowTransform = Callable[[dict[str, Any]], dict[str, Any]]


class SeqStream:
    def __init__(
        self,
        *,
        seed: int,
        name: str,
        generate: RowGenerator,
        page_limit: int,
    ) -> None:
        self.seed = seed
        self.name = name
        self._generate = generate
        self.page_limit = page_limit
        self.released_seq = 0
        self.transform: RowTransform | None = None
        self._lock = threading.Lock()

    def release(self, count: int) -> int:
        with self._lock:
            self.released_seq += count
            return self.released_seq

    def set_page_limit(self, limit: int) -> None:
        with self._lock:
            self.page_limit = limit

    def set_transform(self, transform: RowTransform | None) -> None:
        with self._lock:
            self.transform = transform

    def truth(self, start_seq: int, end_seq: int) -> list[dict[str, Any]]:
        """The rows as generated — what is true regardless of how they are shown."""
        return [self._generate(self.seed, seq) for seq in range(start_seq, end_seq + 1)]

    def rows_after(self, after: int) -> list[dict[str, Any]]:
        """What the API shows: one page of released rows past ``after``."""
        with self._lock:
            released = self.released_seq
            limit = self.page_limit
            transform = self.transform
        start = max(after, 0) + 1
        end = min(released, start + limit - 1)
        rows = self.truth(start, end) if end >= start else []
        if transform is not None:
            rows = [transform(dict(row)) for row in rows]
        return rows


def hash_for(seed: int, name: str, seq: int) -> int:
    return stable_hash(seed, name, seq)
