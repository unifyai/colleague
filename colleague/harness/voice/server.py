"""A local LiveKit server the harness can bring up itself.

The controlled path must not depend on a third-party account, so when no
`LIVEKIT_URL` is configured and a `livekit-server` binary is on PATH, the
harness runs one in dev mode on loopback — the same discipline as the local
fixture servers. Dev mode's well-known key/secret pair is used only ever on
127.0.0.1.

One server per process, started on first need, stopped at exit.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass

DEV_URL = "ws://127.0.0.1:7880"
DEV_HTTP = "http://127.0.0.1:7880"
DEV_KEY = "devkey"
DEV_SECRET = "secret"

_proc: subprocess.Popen | None = None


@dataclass(frozen=True)
class ServerHandle:
    url: str
    api_key: str
    api_secret: str
    managed: bool
    """Whether this process started (and will stop) the server."""


def _responding(http_url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(http_url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 - not up is an ordinary answer
        return False


def _stop() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def ensure_server() -> ServerHandle:
    """A LiveKit server to use: env-configured, already-local, or spawned.

    Priority: an explicit `LIVEKIT_URL` (with `LIVEKIT_API_KEY`/`_SECRET`)
    wins; then a dev server already answering on the default port; then one
    this process spawns. Raises RuntimeError with the reason when none is
    possible — the caller records it and degrades to text.
    """
    global _proc

    env_url = (os.environ.get("LIVEKIT_URL") or "").strip()
    if env_url and env_url != DEV_URL:
        key = (os.environ.get("LIVEKIT_API_KEY") or "").strip()
        secret = (os.environ.get("LIVEKIT_API_SECRET") or "").strip()
        if not (key and secret):
            raise RuntimeError(
                "LIVEKIT_URL is set but LIVEKIT_API_KEY/LIVEKIT_API_SECRET are not",
            )
        return ServerHandle(url=env_url, api_key=key, api_secret=secret, managed=False)

    if _responding(DEV_HTTP):
        return ServerHandle(
            url=DEV_URL,
            api_key=DEV_KEY,
            api_secret=DEV_SECRET,
            managed=_proc is not None,
        )

    import shutil

    binary = shutil.which("livekit-server")
    if not binary:
        raise RuntimeError("no LIVEKIT_URL and no 'livekit-server' on PATH")

    _proc = subprocess.Popen(
        [binary, "--dev", "--bind", "127.0.0.1", "--port", "7880"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(_stop)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _responding(DEV_HTTP):
            return ServerHandle(
                url=DEV_URL,
                api_key=DEV_KEY,
                api_secret=DEV_SECRET,
                managed=True,
            )
        time.sleep(0.25)
    _stop()
    raise RuntimeError("livekit-server was spawned but never answered on :7880")
