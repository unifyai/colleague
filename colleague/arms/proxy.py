"""Recording pass-through proxy for OpenRouter.

A neutral meter for benchmark arms that cannot be instrumented in-process:
the system under test points its OpenAI-compatible ``base_url`` at this
proxy, which forwards every request to https://openrouter.ai unchanged and
records provider-reported usage from the response body — plain JSON and SSE
streams alike (OpenRouter includes a usage payload in the final SSE chunk).
This is the same source of truth the unify arm's in-process hook reads, so
both arms are metered identically: provider-reported tokens per call.

Records one JSONL row per completed request; calls whose response carries no
usage are recorded with ``usage_missing: true`` (never silently dropped),
with a response-tail excerpt for audit.

Run standalone:
    python -m colleague.arms.proxy --port 8124 \
        --ledger /tmp/proxy_ledger.jsonl
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

UPSTREAM = "https://openrouter.ai"

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
}


def _extract_usage_from_json(body: bytes) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    usage = payload.get("usage")
    model = payload.get("model")
    return (usage if isinstance(usage, dict) else None), (str(model) if model else None)


def _extract_usage_from_sse(body: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """Scan SSE data lines back-to-front for the last usage-bearing chunk."""
    usage: dict[str, Any] | None = None
    model: str | None = None
    for raw_line in reversed(body.split(b"\n")):
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[len(b"data:") :].strip()
        if not data or data == b"[DONE]":
            continue
        try:
            chunk = json.loads(data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if model is None and chunk.get("model"):
            model = str(chunk["model"])
        candidate = chunk.get("usage")
        if isinstance(candidate, dict) and candidate:
            usage = candidate
            break
    return usage, model


class ProxyLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._count = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._count += 1
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")

    def count(self) -> int:
        with self._lock:
            return self._count


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ledger: ProxyLedger
    capture: ProxyLedger | None = None

    def _forward(self) -> None:
        t0 = time.time()
        length = int(self.headers.get("Content-Length") or 0)
        request_body = self.rfile.read(length) if length else b""

        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP
        }
        upstream_req = Request(
            f"{UPSTREAM}{self.path}",
            data=request_body if self.command == "POST" else None,
            headers=headers,
            method=self.command,
        )

        request_model = None
        request_stream = False
        if request_body:
            decoded = request_body.decode("utf-8", errors="replace")
            parsed: Any = None
            try:
                parsed = json.loads(decoded)
                if isinstance(parsed, dict):
                    request_model = parsed.get("model")
                    request_stream = bool(parsed.get("stream"))
            except json.JSONDecodeError:
                pass
            if self.capture is not None:
                self.capture.append(
                    {
                        "ts": t0,
                        "path": self.path,
                        "request": parsed if parsed is not None else decoded,
                    },
                )

        response_chunks: list[bytes] = []
        try:
            with urlopen(upstream_req, timeout=1200) as upstream:
                status = upstream.status
                content_type = upstream.headers.get("Content-Type", "")
                self.send_response(status)
                for key, value in upstream.headers.items():
                    if key.lower() in _HOP_BY_HOP or key.lower() == "content-length":
                        continue
                    self.send_header(key, value)
                # Close-delimited body: works for both JSON and SSE without
                # re-chunking, and the OpenAI SDK accepts it over HTTP/1.1.
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break  # client gone; keep reading so usage is recorded
        except Exception as exc:
            status = getattr(exc, "code", 502)
            error_body = b""
            if hasattr(exc, "read"):
                try:
                    error_body = exc.read()
                except Exception:
                    error_body = b""
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(error_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if error_body:
                    self.wfile.write(error_body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.ledger.append(
                {
                    "ts": t0,
                    "path": self.path,
                    "status": status,
                    "error": f"{type(exc).__name__}: {exc}",
                    "request_model": request_model,
                    "usage_missing": True,
                    "latency_s": round(time.time() - t0, 3),
                },
            )
            return
        finally:
            try:
                self.connection.close()
            except Exception:
                pass

        body = b"".join(response_chunks)
        if "text/event-stream" in content_type:
            usage, response_model = _extract_usage_from_sse(body)
        else:
            usage, response_model = _extract_usage_from_json(body)

        record: dict[str, Any] = {
            "ts": t0,
            "path": self.path,
            "status": status,
            "stream": request_stream,
            "request_model": request_model,
            "response_model": response_model,
            "latency_s": round(time.time() - t0, 3),
        }
        if usage:
            record["prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
            record["completion_tokens"] = int(usage.get("completion_tokens") or 0)
            record["total_tokens"] = int(
                usage.get("total_tokens")
                or record["prompt_tokens"] + record["completion_tokens"],
            )
            record["usage_raw"] = usage
        else:
            record["usage_missing"] = True
            record["response_tail"] = body[-400:].decode("utf-8", errors="replace")
        self.ledger.append(record)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._forward()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._forward()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class RecordingProxy:
    def __init__(
        self,
        *,
        port: int,
        ledger_path: Path,
        capture_requests_path: Path | None = None,
    ) -> None:
        self.ledger = ProxyLedger(ledger_path)
        # Verbatim request bodies, when asked for: the metadata ledger says
        # what a call cost, the capture says what the model was actually
        # shown — the evidence a decision autopsy needs. Uniform for every
        # arm behind the proxy, so no arm needs a privileged in-process hook.
        self.capture = (
            ProxyLedger(capture_requests_path) if capture_requests_path else None
        )
        handler = type(
            "BoundProxyHandler",
            (_ProxyHandler,),
            {"ledger": self.ledger, "capture": self.capture},
        )
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        # Handler threads are daemons (http.server default), but ThreadingMixIn
        # still *joins* them in server_close(). A handler stuck reading a hung
        # upstream call — which _ProxyHandler does deliberately after its client
        # is gone, so usage is recorded — would then block stop() for the full
        # 1200s upstream timeout, stalling a scenario teardown for tens of
        # minutes. Close must not wait: a straggler that completes while the
        # process lives still lands in the ledger from its own thread.
        self._server.block_on_close = False
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="openrouter-recording-proxy",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    def start(self) -> "RecordingProxy":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    proxy = RecordingProxy(port=args.port, ledger_path=args.ledger).start()
    print(f"Recording proxy on {proxy.base_url} -> {UPSTREAM} (ledger: {args.ledger})")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        proxy.stop()


if __name__ == "__main__":
    main()
