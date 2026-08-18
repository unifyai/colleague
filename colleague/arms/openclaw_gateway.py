"""OpenClaw's Gateway WebSocket protocol, from the standard library.

The Gateway is OpenClaw's single control plane: every product client — the
CLI, the Control UI, the macOS and mobile apps — speaks JSON frames over a
WebSocket (`docs/gateway/protocol.md`, `packages/gateway-protocol`). This
module is a minimal operator client for it: RFC 6455 client framing, the
`connect` handshake, request/response correlation and an event fan-out, in
stdlib Python so the arm reproduces without installing anything from this
project (`pyproject.toml`: the harness and every comparison-arm driver are
stdlib-only on purpose).

Frame shapes, verbatim from the protocol doc:

    request   {"type": "req",   "id", "method", "params"}
    response  {"type": "res",   "id", "ok", "payload" | "error"}
    event     {"type": "event", "event", "payload", "seq"?}

Authentication is the shared gateway token on loopback. OpenClaw's own CLI
omits the device identity block exactly in that case (`src/gateway/call.ts`,
`shouldOmitDeviceIdentityForGatewayCall`: local CLI client + shared-secret
auth + loopback URL), so this client connects as `client.id: "cli"` the same
way and needs no ed25519 signing. The Gateway keeps a device-less client's
requested operator scopes only on that first-party local CLI path
(`handshake-auth-helpers.ts`, `shouldPreserveLocalCliSharedAuthScopes`),
which is also why the upgrade request carries no browser `Origin` header:
an Origin makes the connection a browser-class client and clears its
scopes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

PROTOCOL_VERSION = 4

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class GatewayError(RuntimeError):
    """A Gateway RPC failed: error response, timeout, or the socket closed."""


class _Pending:
    __slots__ = ("event", "frame")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.frame: dict[str, Any] | None = None


class _WebSocket:
    """One client-side WebSocket over a plain TCP socket (ws:// only)."""

    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        parts = urlsplit(url)
        if parts.scheme != "ws":
            raise GatewayError(f"only ws:// is supported here, got {url!r}")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 80
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self._sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise GatewayError("websocket handshake: connection closed")
            response += chunk
        head, _, rest = response.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status_line:
            raise GatewayError(f"websocket handshake failed: {status_line}")
        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest(),
        ).decode()
        accept = ""
        for line in head.decode(errors="replace").split("\r\n")[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "sec-websocket-accept":
                accept = value.strip()
        if accept != expected:
            raise GatewayError("websocket handshake: bad Sec-WebSocket-Accept")
        self._buffer = rest
        self._send_lock = threading.Lock()
        self._sock.settimeout(None)

    # -- framing ---------------------------------------------------------

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def send_close(self) -> None:
        try:
            self._send_frame(0x8, struct.pack("!H", 1000))
        except OSError:
            pass

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(bytes(header) + masked)

    def _read_exact(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def recv_text(self) -> str | None:
        """Next complete text message, or None once the peer has closed."""
        fragments: list[bytes] = []
        while True:
            b1, b2 = self._read_exact(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack("!H", self._read_exact(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", self._read_exact(8))
            mask = self._read_exact(4) if b2 & 0x80 else b""
            payload = self._read_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                return None
            if opcode == 0x9:  # ping
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x0):
                fragments.append(payload)
                if fin:
                    return b"".join(fragments).decode("utf-8", errors="replace")
                continue
            # Binary frames are not part of the operator protocol; skip.
            if fin:
                fragments = []

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class GatewayClient:
    """An authenticated operator connection to one Gateway."""

    def __init__(
        self,
        url: str,
        *,
        token: str,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        log: Callable[[str, dict[str, Any]], None] | None = None,
        client_id: str = "cli",
        client_mode: str = "cli",
        display_name: str | None = None,
        # `operator.questions` is what `question.*` RPCs need *and* what gates
        # the `question.requested` broadcast (server-broadcast.ts): without
        # it an ask_user question is asked and no client ever hears it.
        scopes: tuple[str, ...] = (
            "operator.read",
            "operator.write",
            "operator.approvals",
            "operator.questions",
        ),
        connect_timeout: float = 60.0,
    ) -> None:
        self.url = url
        self._token = token
        self._on_event = on_event
        self._log = log
        self._client_id = client_id
        self._client_mode = client_mode
        self._display_name = display_name
        self._scopes = scopes
        self._ws: _WebSocket | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._alive = False
        self._challenge = threading.Event()
        self._challenge_payload: dict[str, Any] = {}
        self.hello: dict[str, Any] = {}
        self._connect_timeout = connect_timeout

    # -- lifecycle -------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        self._ws = _WebSocket(self.url, timeout=self._connect_timeout)
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_loop,
            name="openclaw-gateway-reader",
            daemon=True,
        )
        self._reader.start()
        # The Gateway sends `connect.challenge` first; a token client may
        # ignore its nonce, but waiting for it keeps the handshake ordered.
        self._challenge.wait(timeout=10.0)
        client: dict[str, Any] = {
            "id": self._client_id,
            "version": "colleague-bench",
            "platform": "darwin" if os.uname().sysname == "Darwin" else "linux",
            "mode": self._client_mode,
        }
        if self._display_name:
            client["displayName"] = self._display_name
        params = {
            "minProtocol": PROTOCOL_VERSION,
            "maxProtocol": PROTOCOL_VERSION,
            "client": client,
            "role": "operator",
            "scopes": list(self._scopes),
            "caps": [],
            "auth": {"token": self._token},
            "userAgent": "colleague-bench/openclaw-gateway",
        }
        deadline = time.monotonic() + self._connect_timeout
        while True:
            try:
                self.hello = self.call("connect", params, timeout=self._connect_timeout)
                return self.hello
            except GatewayError as exc:
                # Startup sidecars: the doc says retry within the budget.
                if "UNAVAILABLE" in str(exc) and time.monotonic() < deadline:
                    time.sleep(1.0)
                    continue
                raise

    def close(self) -> None:
        self._alive = False
        ws = self._ws
        if ws is not None:
            ws.send_close()
            ws.close()
        self._ws = None

    @property
    def alive(self) -> bool:
        return self._alive

    # -- rpc -------------------------------------------------------------

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        ws = self._ws
        if ws is None or not self._alive:
            raise GatewayError(f"{method}: gateway connection is not open")
        rid = secrets.token_hex(8)
        pending = _Pending()
        with self._pending_lock:
            self._pending[rid] = pending
        frame = {"type": "req", "id": rid, "method": method, "params": params or {}}
        try:
            self._emit_log("send", frame)
            ws.send_text(json.dumps(frame, ensure_ascii=False))
            if not pending.event.wait(timeout):
                raise GatewayError(f"{method} timed out after {timeout}s")
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)
        resp = pending.frame or {}
        if not resp.get("ok"):
            err = resp.get("error") or {}
            raise GatewayError(
                f"{method} failed: {err.get('code')} {err.get('message')} "
                f"{json.dumps(err.get('details')) if err.get('details') else ''}".strip(),
            )
        payload = resp.get("payload")
        return payload if isinstance(payload, dict) else {"payload": payload}

    # -- reader ----------------------------------------------------------

    def _read_loop(self) -> None:
        ws = self._ws
        assert ws is not None
        try:
            while self._alive:
                text = ws.recv_text()
                if text is None:
                    break
                try:
                    frame = json.loads(text)
                except json.JSONDecodeError:
                    self._emit_log("recv_raw", {"line": text[:2000]})
                    continue
                if not isinstance(frame, dict):
                    continue
                self._emit_log("recv", frame)
                kind = frame.get("type")
                if kind == "res":
                    with self._pending_lock:
                        pending = self._pending.get(str(frame.get("id")))
                    if pending is not None:
                        pending.frame = frame
                        pending.event.set()
                elif kind == "event":
                    name = str(frame.get("event") or "")
                    payload = frame.get("payload")
                    payload = payload if isinstance(payload, dict) else {}
                    if name == "connect.challenge":
                        self._challenge_payload = payload
                        self._challenge.set()
                    if self._on_event is not None:
                        try:
                            self._on_event(name, payload)
                        except Exception:  # noqa: BLE001 - reader must survive
                            pass
        except (ConnectionError, OSError):
            pass
        finally:
            self._alive = False
            with self._pending_lock:
                for pending in self._pending.values():
                    pending.frame = {
                        "ok": False,
                        "error": {
                            "code": "CLOSED",
                            "message": "gateway connection closed",
                        },
                    }
                    pending.event.set()
                self._pending.clear()

    def _emit_log(self, direction: str, frame: dict[str, Any]) -> None:
        if self._log is None:
            return
        try:
            self._log(direction, frame)
        except Exception:  # noqa: BLE001 - logging must never break a call
            pass


def assistant_text(message: Any) -> str:
    """The visible text of a chat event's assistant message.

    Chat `final` payloads carry the assistant message as OpenClaw stores it:
    ``{"role": "assistant", "content": [{"type": "text", "text": ...}, ...]}``
    or a plain string. Tool-only or silent finals carry none.
    """
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in (
                "text",
                "output_text",
            ):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    text = message.get("text")
    return text if isinstance(text, str) else ""
