"""Attachments ride the channels: a person shares a file, and expects one back.

The document-scale regime retires the seeded fixture APIs. What replaces
them is the way real work actually moves — Daniel attaches this week's
documents to his message, and the finished spreadsheet comes back to him
as a file. This module is the shared vocabulary for that, in both
directions, with the fixture kept as the only witness.

**Inbound** (person → arm): a scenario stages files and every surface
receives them through its own best mechanism — the unify CM ingests them
on its product channel the way any chat attachment arrives, CLI arms find
them materialised in their session workspace with the message saying so,
the mock plan gets the paths, and the human sees download links. The one
sentence that tells a workspace arm where its files landed is composed
here, once, so no arm is quietly told more than another.

**Outbound** (arm → fixture): whatever channel carried the produced file —
a product send with an attachment, a reply naming a path in the arm's own
workspace — the artifact lands with the fixture through the `/deliver`
witness route and is scored from there. Like `/reply`, the route is never
documented to the arm: it is the bridge's business, not a capability. An
arm that names no path still gets its newest produced file collected,
because "said nothing but did the work" is a wording difference, not an
outcome difference; how the file was found is recorded either way.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Callable

from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
)

#: File suffixes a deliverable may carry, in collection-preference order.
DELIVERABLE_SUFFIXES = (".xlsx", ".csv")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def attachment_note(paths: list[str | Path]) -> str:
    """The one sentence telling a workspace arm where its files landed.

    Composed in exactly one place for the same reason `session.compose`
    exists: no arm may be quietly handed a richer description of the
    attachments than another. Names only what the chat surface itself
    would show — the files, where they were saved.
    """
    if not paths:
        return ""
    lines = "\n".join(f"  {p}" for p in map(str, paths))
    return f"[Attached files, saved to your machine at:\n{lines}\n]"


def materialize(paths: list[str | Path], dest: Path) -> list[Path]:
    """Copy staged files into an arm's workspace, returning the new paths."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for p in map(Path, paths):
        target = dest / p.name
        shutil.copyfile(p, target)
        out.append(target)
    return out


def deliver_route(fx: FixtureServer, artifact_dir: str | Path | None = None) -> None:
    """Mount the `/deliver` witness route on a fixture.

    The bridge (the CM adapter for a product send carrying an attachment,
    the runner for a file collected from a workspace) POSTs
    ``{"filename", "content_b64", "via", "note"?}``; bytes land under
    ``artifact_dir`` and the recorder keeps filename, sha and stored path.
    The runner points ``state["artifact_dir"]`` into the run's results
    tree before any scenario; a fixture built outside a run falls back to
    a temp directory. Deliberately absent from anything an arm reads — a
    documented upload endpoint would be the `/clarify` mistake with a
    file attached.
    """
    if artifact_dir:
        fx.state["artifact_dir"] = str(artifact_dir)

    def deliver(r: Request) -> tuple[int, Any]:
        missing = missing_fields(r.body, "filename", "content_b64", "via")
        if missing:
            return reject(r.server, "deliver", r.body, missing)
        try:
            content = base64.b64decode(r.body["content_b64"], validate=True)
        except Exception:  # noqa: BLE001 - malformed base64 is a 400, not a crash
            return reject(r.server, "deliver", r.body, ["content_b64"])
        if not r.server.state.get("artifact_dir"):
            import tempfile

            r.server.state["artifact_dir"] = tempfile.mkdtemp(
                prefix="colleague-deliverables-",
            )
        out_dir = Path(r.server.state["artifact_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        seq_hint = r.server.recorder.count("deliver") + 1
        filename = Path(str(r.body["filename"])).name
        stored = out_dir / f"{seq_hint:03d}-{filename}"
        stored.write_bytes(content)
        r.server.recorder.record(
            "deliver",
            {
                "filename": filename,
                "via": r.body["via"],
                "note": str(r.body.get("note") or ""),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "stored_path": str(stored),
            },
        )
        return 200, {"status": "received"}

    fx.route("POST", "/deliver", deliver)


def post_deliverable(
    base_url: str,
    path: str | Path,
    *,
    via: str,
    note: str = "",
) -> None:
    """Bridge one produced file to the fixture's `/deliver` witness."""
    payload = {
        "filename": Path(path).name,
        "content_b64": base64.b64encode(Path(path).read_bytes()).decode(),
        "via": via,
        "note": note,
    }
    req = urllib.request.Request(
        f"{base_url}/deliver",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


_PATH_TOKEN = re.compile(r"[\w./~-]+\.(?:xlsx|csv)\b", re.IGNORECASE)


def find_deliverable(
    reply_text: str,
    roots: list[Path],
    *,
    ignore: Callable[[Path], bool] | None = None,
    since: float | None = None,
) -> tuple[Path | None, str]:
    """The produced file a workspace arm is handing back, and how it was found.

    Two honest readings of a reply, in order: a path the arm itself named
    (resolved inside one of ``roots``), else the newest deliverable-suffixed
    file under the roots — an arm that silently saved the work still did
    the work. ``ignore`` filters files the harness itself put there (the
    inbound attachments), so an arm can never hand back its own inputs by
    doing nothing; ``since`` limits *discovery* (never an explicitly named
    path) to files modified after it, so old work cannot be re-collected.
    Returns ``(None, "")`` when nothing qualifies, which is the scorer's
    evidence, not an error.
    """
    ignore = ignore or (lambda _p: False)

    def resolved(candidate: str) -> Path | None:
        name = Path(candidate).expanduser()
        tries = [name] if name.is_absolute() else [root / name for root in roots]
        tries += [root / name.name for root in roots]
        for t in tries:
            try:
                t = t.resolve()
            except OSError:
                continue
            if not t.is_file() or ignore(t):
                continue
            if any(t.is_relative_to(root.resolve()) for root in roots):
                return t
        return None

    for token in _PATH_TOKEN.findall(reply_text or ""):
        hit = resolved(token)
        if hit is not None:
            return hit, "named_in_reply"

    newest: Path | None = None
    for root in roots:
        if not root.is_dir():
            continue
        for suffix in DELIVERABLE_SUFFIXES:
            for p in root.rglob(f"*{suffix}"):
                if not p.is_file() or ignore(p.resolve()):
                    continue
                if since is not None and p.stat().st_mtime < since:
                    continue
                if newest is None or p.stat().st_mtime > newest.stat().st_mtime:
                    newest = p
    if newest is not None:
        return newest, "discovered_in_workspace"
    return None, ""
