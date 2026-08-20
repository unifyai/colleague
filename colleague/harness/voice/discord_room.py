"""A Discord voice channel the harness owns: hermes's voice substrate.

hermes's real voice surface is Discord voice — its `DiscordAdapter` joins a
guild voice channel through `discord.py`, attributes speakers per-SSRC, and
speaks its replies back as Opus. That is the surface `meeting` measures for
this arm, so the harness stands up a **Discord-protocol-compatible server on
loopback** and lets hermes's own client connect to it: a REST endpoint, a
gateway WebSocket, a voice WebSocket, and a UDP media socket, all faithful
enough to `discord.py` 2.7.1 that the arm joins a voice channel and holds a
spoken conversation without knowing it is not talking to Discord.

The contract (README §"Why LiveKit…"): the arm joins *its own* substrate's
room with its own identity; the harness owns the persona voices and the
capture on that substrate. Here the personas are distinct Discord users, each
publishing Opus on its own SSRC (so per-speaker attribution is the real
problem hermes must solve), and the assistant's utterance text is taken from
the arm where it speaks from text — hermes posts every reply to the channel
as it speaks it (`POST /channels/{id}/messages`), which is the exact string,
never a transcription. The bot's own audio is captured for the transport
timestamps and kept as a transcript cross-check.

No third-party account and no TLS: `discord.py`'s gateway URL and REST base
are class constants a `sitecustomize` shim repoints at this server, and its
one `wss://`-only path (the voice gateway) is rewritten to `ws://` on
loopback by the same shim (see `write_sitecustomize`). Everything runs on
127.0.0.1, the same discipline as the fixture servers.

Wire specifics are `discord.py` 2.7.1's, read from the pinned library:
gateway v10 (plain-text frames accepted — the inflater only touches binary),
voice gateway v8 with `seq_ack` heartbeats, IP discovery as a 74-byte probe,
and RTP encrypted with `aead_xchacha20_poly1305_rtpsize` (a 4-byte counter
nonce suffix, the 12-byte header as AEAD associated data) — the one mode the
server offers, which is also hermes's only receive mode.
"""

from __future__ import annotations

import asyncio
import audioop
import json
import secrets
import socket
import struct
import threading
from typing import Any, Callable

from colleague.harness.voice.room import RoomInvite
from colleague.harness.voice.substrate import SubstrateVoiceRoom
from colleague.harness.voice.tts import SAMPLE_RATE, SAMPLE_WIDTH, VoiceBank

# ---------------------------------------------------------------- identities

#: Fixed snowflakes for the harness's cast. Real Discord ids are 64-bit
#: snowflakes; any distinct integers serialize the same over the wire.
_BOT_USER_ID = 900000000000000001
_GUILD_ID = 900000000000000010
_TEXT_CHANNEL_ID = 900000000000000020
_VOICE_CHANNEL_ID = 900000000000000030
_APP_ID = 900000000000000040

#: SSRCs. The bot's is what hermes advertises and self-filters on; personas
#: get their own so hermes attributes each utterance to a distinct speaker.
_BOT_SSRC = 555
_PERSONA_SSRC_BASE = 1001

# --------------------------------------------------------------------- audio

_OPUS_FRAME_SAMPLES = 960  # 20 ms at 48 kHz, discord's native tick
_OPUS_FRAME_S = 0.02
_OPUS_SILENCE = b"\xf8\xff\xfe"  # the bare Opus silence frame hermes keepalives with


def _persona_user_id(index: int) -> int:
    return 900000000000001000 + index


def _json(payload: Any, status: int = 200) -> Any:
    """A JSON response with a bare `application/json` content-type.

    discord.py 2.7.1 decodes a body only when the content-type is *exactly*
    `application/json` (http.py:113); aiohttp's `json_response` appends
    `; charset=utf-8`, which would make the client hand back the raw text.
    """
    import json as _j

    from aiohttp import web

    return web.Response(
        body=_j.dumps(payload).encode(),
        status=status,
        content_type="application/json",
    )


class _LoopThread:
    """An asyncio loop on its own thread; the server lives entirely on it."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="discord-srv", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def run(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    def call_soon(self, fn) -> None:
        self.loop.call_soon_threadsafe(fn)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class FakeDiscordServer:
    """The loopback Discord: REST + gateway WS + voice WS + UDP media.

    One bot client (hermes) and a fixed cast of persona users. The server is
    deliberately minimal — it implements exactly the calls `discord.py` 2.7.1
    makes on the join-a-voice-channel-and-speak path, and answers everything
    else benignly.
    """

    def __init__(
        self,
        *,
        personas: list[str],
        on_reply: Callable[[str], None],
        on_bot_pcm: Callable[[bytes], None],
    ) -> None:
        self.personas = list(personas)
        self._on_reply = on_reply
        self._on_bot_pcm = on_bot_pcm
        self.secret_key = list(secrets.token_bytes(32))
        self._key = bytes(self.secret_key)
        self._persona_ids = {
            p: _persona_user_id(i) for i, p in enumerate(self.personas)
        }
        self._persona_ssrc = {
            p: _PERSONA_SSRC_BASE + i for i, p in enumerate(self.personas)
        }
        self._loop = _LoopThread()

        self._http_port = 0
        self._gw_port = 0
        self._voice_ws_port = 0
        self._udp_port = 0

        self._gw_ws: Any = None  # the bot's gateway connection
        self._gw_seq = 0
        self._identified = threading.Event()
        self._voice_connected = threading.Event()
        self._session_id = secrets.token_hex(8)
        self._voice_session_id = secrets.token_hex(8)
        self._voice_token = secrets.token_hex(8)

        self._udp_transport: Any = None
        self._bot_addr: tuple[str, int] | None = None
        self._recv_state: Any = None  # audioop.ratecv state for 48k stereo->mono
        self._decoders: dict[int, Any] = {}

        self._runner: Any = None
        self._gw_server: Any = None
        self._voice_server: Any = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._loop.run(self._start())

    async def _start(self) -> None:
        from aiohttp import web
        from websockets.asyncio.server import serve

        # REST
        app = web.Application()
        app.router.add_route("GET", "/api/v10/users/@me", self._rest_me)
        app.router.add_route("GET", "/api/v{ver}/users/@me", self._rest_me)
        app.router.add_route(
            "GET", "/api/v{ver}/oauth2/applications/@me", self._rest_app
        )
        app.router.add_route("GET", "/api/v10/oauth2/applications/@me", self._rest_app)
        app.router.add_route(
            "POST", "/api/v{ver}/channels/{cid}/messages", self._rest_message
        )
        app.router.add_route("*", "/{tail:.*}", self._rest_catchall)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._http_port = site._server.sockets[0].getsockname()[1]

        # Gateway + voice WS
        self._gw_server = await serve(self._gateway_handler, "127.0.0.1", 0)
        self._gw_port = self._gw_server.sockets[0].getsockname()[1]
        self._voice_server = await serve(self._voice_handler, "127.0.0.1", 0)
        self._voice_ws_port = self._voice_server.sockets[0].getsockname()[1]

        # UDP media
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.bind(("127.0.0.1", 0))
        self._udp_port = udp_sock.getsockname()[1]
        self._udp_transport, _ = await self._loop.loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self),
            sock=udp_sock,
        )

    def close(self) -> None:
        try:
            self._loop.run(self._stop(), timeout=10)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        self._loop.close()

    async def _stop(self) -> None:
        # Close the arm's live sockets first, then the servers, and wait for
        # each to settle before the loop thread stops — otherwise pending
        # websockets read tasks are torn down mid-flight and log "Event loop
        # is closed" tracebacks into the run's artifacts.
        for ws in (self._gw_ws, self._voice_ws):
            if ws is not None:
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._udp_transport is not None:
            self._udp_transport.close()
        for server in (self._gw_server, self._voice_server):
            if server is not None:
                server.close()
                try:
                    await server.wait_closed()
                except Exception:  # noqa: BLE001
                    pass
        if self._runner is not None:
            await self._runner.cleanup()
        # Let any callbacks the closes scheduled run before the loop stops.
        await asyncio.sleep(0.1)

    # ------------------------------------------------------------------ REST

    async def _rest_me(self, request: Any) -> Any:
        return _json(
            {
                "id": str(_BOT_USER_ID),
                "username": "colleague-assistant",
                "discriminator": "0001",
                "avatar": None,
                "bot": True,
                "verified": True,
                "flags": 0,
            },
        )

    async def _rest_app(self, request: Any) -> Any:
        return _json(
            {
                "id": str(_APP_ID),
                "name": "colleague-assistant",
                "description": "",
                "icon": None,
                "bot_public": False,
                "bot_require_code_grant": False,
                "verify_key": "0" * 64,
                "owner": {
                    "id": str(_BOT_USER_ID),
                    "username": "colleague",
                    "discriminator": "0001",
                    "avatar": None,
                },
                "flags": 0,
            },
        )

    async def _rest_message(self, request: Any) -> Any:
        cid = request.match_info.get("cid", "0")
        content = await self._message_content(request)
        if content:
            # Hermes echoes each heard line as "**[Voice]** <@id>: …"; those
            # are not the assistant speaking, they are it repeating a persona.
            if not content.startswith("**[Voice]**"):
                try:
                    self._on_reply(content)
                except Exception:  # noqa: BLE001 - capture must never 500 the arm
                    pass
        return _json(_message_object(cid, content))

    async def _message_content(self, request: Any) -> str:
        """The `content` of a message create, JSON or multipart.

        discord.py sends a plain reply as JSON; a reply it also voices sends
        the text as the `payload_json` field of a multipart upload (the audio
        rides alongside). Both carry the exact words in `content`.
        """
        ctype = request.headers.get("Content-Type", "")
        if ctype.startswith("application/json"):
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 - malformed; nothing to tap
                return ""
            return str((body or {}).get("content") or "")
        if ctype.startswith("multipart/"):
            # Read the raw body and pull `payload_json` out by hand rather
            # than aiohttp's multipart parser, which stalled on the arm's
            # attachment uploads (leaving the arm's HTTP client hung on the
            # POST for minutes). Bounded by aiohttp's client_max_size.
            try:
                raw = await request.read()
            except Exception:  # noqa: BLE001 - unreadable body; nothing to tap
                return ""
            return _payload_json_content(raw)
        return ""

    async def _rest_catchall(self, request: Any) -> Any:
        # Everything else discord.py might probe (guild/channel reads, command
        # sync when not disabled, edits of its own streaming placeholder):
        # answer with a valid JSON body so no client-side decode raises. A
        # message route gets a message object; anything else an empty object.
        # Message *edits* are ignored for capture — the final reply is always
        # posted as a fresh create, which `_rest_message` taps.
        path = request.path
        if "/messages/" in path or path.endswith("/messages"):
            return _json(_message_object("0", ""))
        return _json({})

    # --------------------------------------------------------------- gateway

    async def _gateway_handler(self, ws: Any) -> None:
        self._gw_ws = ws
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 41250}}))
        try:
            async for raw in ws:
                msg = json.loads(raw)
                op = msg.get("op")
                if op == 2:  # IDENTIFY
                    await self._send_ready(ws)
                    self._identified.set()
                elif op == 1:  # HEARTBEAT
                    await ws.send(json.dumps({"op": 11}))
                elif op == 4:  # VOICE_STATE (bot joining/leaving a channel)
                    await self._on_voice_state(ws, msg.get("d") or {})
                elif op == 6:  # RESUME — treat as a fresh READY
                    await self._send_ready(ws)
        except Exception:  # noqa: BLE001 - a dropped socket ends this client
            pass

    async def _send_ready(self, ws: Any) -> None:
        self._gw_seq += 1
        user = {
            "id": str(_BOT_USER_ID),
            "username": "colleague-assistant",
            "discriminator": "0001",
            "avatar": None,
            "bot": True,
        }
        ready = {
            "op": 0,
            "s": self._gw_seq,
            "t": "READY",
            "d": {
                "v": 10,
                "user": user,
                "guilds": [{"id": str(_GUILD_ID), "unavailable": True}],
                "session_id": self._session_id,
                "resume_gateway_url": f"ws://127.0.0.1:{self._gw_port}",
                "application": {"id": str(_APP_ID), "flags": 0},
            },
        }
        await ws.send(json.dumps(ready))
        await self._send_guild_create(ws)

    async def _send_guild_create(self, ws: Any) -> None:
        self._gw_seq += 1
        members = [
            {
                "user": {
                    "id": str(self._persona_ids[p]),
                    "username": p,
                    "discriminator": "0002",
                    "avatar": None,
                },
                "nick": p,
                "roles": [],
                "joined_at": "2020-01-01T00:00:00+00:00",
                "deaf": False,
                "mute": False,
                "flags": 0,
            }
            for p in self.personas
        ]
        voice_states = [
            {
                "user_id": str(self._persona_ids[p]),
                "channel_id": str(_VOICE_CHANNEL_ID),
                "session_id": secrets.token_hex(8),
                "deaf": False,
                "mute": False,
                "self_deaf": False,
                "self_mute": False,
                "self_video": False,
                "suppress": False,
            }
            for p in self.personas
        ]
        guild = {
            "op": 0,
            "s": self._gw_seq,
            "t": "GUILD_CREATE",
            "d": {
                "id": str(_GUILD_ID),
                "name": "colleague",
                "owner_id": str(self._persona_ids[self.personas[0]]),
                "unavailable": False,
                "member_count": len(members) + 1,
                "roles": [
                    {
                        "id": str(_GUILD_ID),  # @everyone
                        "name": "@everyone",
                        "permissions": str((1 << 3)),  # Administrator, for simplicity
                        "position": 0,
                        "color": 0,
                        "hoist": False,
                        "managed": False,
                        "mentionable": False,
                    },
                ],
                "channels": [
                    {
                        "id": str(_TEXT_CHANNEL_ID),
                        "type": 0,  # GUILD_TEXT
                        "name": "planning",
                        "position": 0,
                        "permission_overwrites": [],
                    },
                    {
                        "id": str(_VOICE_CHANNEL_ID),
                        "type": 2,  # GUILD_VOICE
                        "name": "planning-call",
                        "position": 1,
                        "permission_overwrites": [],
                        "bitrate": 64000,
                        "user_limit": 0,
                        "rtc_region": None,
                        "nsfw": False,
                    },
                ],
                "members": members,
                "voice_states": voice_states,
                "emojis": [],
                "features": [],
            },
        }
        await ws.send(json.dumps(guild))

    async def _on_voice_state(self, ws: Any, d: dict[str, Any]) -> None:
        channel_id = d.get("channel_id")
        if channel_id is None:
            return  # the bot leaving; no server-update needed
        # Echo the bot's own voice state, then point it at our voice gateway.
        self._gw_seq += 1
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": self._gw_seq,
                    "t": "VOICE_STATE_UPDATE",
                    "d": {
                        "guild_id": str(_GUILD_ID),
                        "channel_id": str(_VOICE_CHANNEL_ID),
                        "user_id": str(_BOT_USER_ID),
                        "session_id": self._voice_session_id,
                        "deaf": False,
                        "mute": False,
                        "self_deaf": False,
                        "self_mute": False,
                        "self_video": False,
                        "suppress": False,
                    },
                },
            ),
        )
        self._gw_seq += 1
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": self._gw_seq,
                    "t": "VOICE_SERVER_UPDATE",
                    "d": {
                        "token": self._voice_token,
                        "guild_id": str(_GUILD_ID),
                        "endpoint": f"127.0.0.1:{self._voice_ws_port}",
                    },
                },
            ),
        )

    def deliver_message(self, content: str, sender: str) -> None:
        """Dispatch a MESSAGE_CREATE from a persona into the text channel."""
        self._loop.call_soon(
            lambda: asyncio.ensure_future(self._deliver_message(content, sender)),
        )

    async def _deliver_message(self, content: str, sender: str) -> None:
        ws = self._gw_ws
        if ws is None:
            return
        uid = self._persona_ids.get(sender, self._persona_ids[self.personas[0]])
        self._gw_seq += 1
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": self._gw_seq,
                    "t": "MESSAGE_CREATE",
                    "d": {
                        "id": str(secrets.randbits(63)),
                        "type": 0,
                        "channel_id": str(_TEXT_CHANNEL_ID),
                        "guild_id": str(_GUILD_ID),
                        "content": content,
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "edited_timestamp": None,
                        "tts": False,
                        "mention_everyone": False,
                        "mentions": [],
                        "mention_roles": [],
                        "attachments": [],
                        "embeds": [],
                        "pinned": False,
                        "author": {
                            "id": str(uid),
                            "username": sender,
                            "discriminator": "0002",
                            "avatar": None,
                            "bot": False,
                        },
                        "member": {
                            "nick": sender,
                            "roles": [],
                            "joined_at": "2020-01-01T00:00:00+00:00",
                            "deaf": False,
                            "mute": False,
                            "flags": 0,
                        },
                    },
                },
            ),
        )

    # ----------------------------------------------------------- voice gateway

    async def _voice_handler(self, ws: Any) -> None:
        self._voice_ws = ws
        try:
            async for raw in ws:
                msg = json.loads(raw)
                op = msg.get("op")
                if op == 0:  # IDENTIFY
                    await ws.send(
                        json.dumps({"op": 8, "d": {"heartbeat_interval": 13750}}),
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "op": 2,
                                "d": {
                                    "ssrc": _BOT_SSRC,
                                    "ip": "127.0.0.1",
                                    "port": self._udp_port,
                                    "modes": ["aead_xchacha20_poly1305_rtpsize"],
                                    "heartbeat_interval": 13750,
                                },
                            },
                        ),
                    )
                elif op == 1:  # SELECT_PROTOCOL
                    await ws.send(
                        json.dumps(
                            {
                                "op": 4,
                                "d": {
                                    "mode": "aead_xchacha20_poly1305_rtpsize",
                                    "secret_key": self.secret_key,
                                    "dave_protocol_version": 0,
                                },
                            },
                        ),
                    )
                    self._voice_connected.set()
                elif op == 3:  # HEARTBEAT
                    d = msg.get("d")
                    t = d.get("t") if isinstance(d, dict) else d
                    await ws.send(json.dumps({"op": 6, "d": t}))
                elif op == 5:  # SPEAKING (the bot announcing it will speak)
                    self._voice_connected.set()
        except Exception:  # noqa: BLE001 - a dropped voice socket ends the call
            pass

    async def _speak_persona(self, ssrc: int, uid: int, speaking: bool) -> None:
        """Tell the bot which user an SSRC belongs to, before its audio."""
        ws = self._voice_ws
        if ws is None:
            return
        await ws.send(
            json.dumps(
                {
                    "op": 5,
                    "d": {
                        "speaking": 1 if speaking else 0,
                        "delay": 0,
                        "ssrc": ssrc,
                        "user_id": str(uid),
                    },
                },
            ),
        )

    # -------------------------------------------------------------- capture

    def handle_rtp(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called from the UDP protocol for every datagram the bot sends."""
        # IP-discovery probe: 74 bytes, type 0x0001.
        if len(data) == 74 and data[0] == 0x00 and data[1] == 0x01:
            self._bot_addr = addr
            self._respond_ip_discovery(addr)
            return
        if len(data) < 12:
            return  # keepalive silence frame or noise
        pt = data[1]
        if pt != 0x78:
            return
        ssrc = struct.unpack_from(">I", data, 8)[0]
        if ssrc != _BOT_SSRC:
            return
        self._bot_addr = addr
        opus = self._decrypt(data)
        if not opus or opus == _OPUS_SILENCE:
            return
        pcm = self._decode_opus(ssrc, opus)
        if pcm:
            try:
                self._on_bot_pcm(pcm)
            except Exception:  # noqa: BLE001 - capture must not kill the reader
                pass

    def _respond_ip_discovery(self, addr: tuple[str, int]) -> None:
        packet = struct.pack(">HHI", 0x0002, 70, _BOT_SSRC)
        packet += b"127.0.0.1".ljust(64, b"\x00")
        packet += struct.pack(">H", self._udp_port)
        if self._udp_transport is not None:
            self._udp_transport.sendto(packet, addr)

    def _decrypt(self, data: bytes) -> bytes:
        import nacl.secret

        try:
            header = data[:12]
            nonce = bytes(data[-4:]) + b"\x00" * 20
            ciphertext = data[12:-4]
            box = nacl.secret.Aead(self._key)
            return box.decrypt(ciphertext, header, nonce)
        except Exception:  # noqa: BLE001 - a bad packet is dropped
            return b""

    def _decode_opus(self, ssrc: int, opus: bytes) -> bytes:
        import av

        dec = self._decoders.get(ssrc)
        if dec is None:
            dec = av.CodecContext.create("opus", "r")
            self._decoders[ssrc] = dec
        try:
            out = bytearray()
            for frame in dec.decode(av.Packet(opus)):
                arr = frame.to_ndarray()  # (channels, samples) or (1, samples*ch)
                pcm = _frame_to_s16_mono_48k(frame, arr)
                out.extend(pcm)
            return bytes(out)
        except Exception:  # noqa: BLE001 - a decode error drops one frame
            return b""

    # ---------------------------------------------------------------- sending

    def send_persona_opus(self, who: str, opus_frames: list[bytes]) -> None:
        """Play one persona line: announce the SSRC, then pace RTP frames."""
        ssrc = self._persona_ssrc[who]
        uid = self._persona_ids[who]
        self._loop.run(self._send_persona_opus(ssrc, uid, opus_frames), timeout=180)

    async def _send_persona_opus(
        self,
        ssrc: int,
        uid: int,
        opus_frames: list[bytes],
    ) -> None:
        if self._bot_addr is None:
            return
        await self._speak_persona(ssrc, uid, True)
        seq = secrets.randbits(16)
        ts = secrets.randbits(32)
        t0 = self._loop.loop.time()
        for i, opus in enumerate(opus_frames):
            packet = self._encrypt(seq, ts, ssrc, opus)
            if self._udp_transport is not None and self._bot_addr is not None:
                self._udp_transport.sendto(packet, self._bot_addr)
            seq = (seq + 1) & 0xFFFF
            ts = (ts + _OPUS_FRAME_SAMPLES) & 0xFFFFFFFF
            await asyncio.sleep(
                max(0.0, t0 + (i + 1) * _OPUS_FRAME_S - self._loop.loop.time())
            )
        await self._speak_persona(ssrc, uid, False)

    _incr_nonce = 0

    def _encrypt(self, seq: int, ts: int, ssrc: int, opus: bytes) -> bytes:
        import nacl.secret

        header = bytearray(12)
        header[0] = 0x80
        header[1] = 0x78
        struct.pack_into(">H", header, 2, seq)
        struct.pack_into(">I", header, 4, ts)
        struct.pack_into(">I", header, 8, ssrc)
        nonce = bytearray(24)
        struct.pack_into(">I", nonce, 0, self._incr_nonce)
        self._incr_nonce = (self._incr_nonce + 1) & 0xFFFFFFFF
        box = nacl.secret.Aead(self._key)
        ct = box.encrypt(opus, bytes(header), bytes(nonce)).ciphertext
        return bytes(header) + ct + bytes(nonce[:4])

    # The voice WS reference, set by the handler on connect.
    _voice_ws: Any = None

    # ------------------------------------------------------------ accessors

    @property
    def gateway_url(self) -> str:
        return f"ws://127.0.0.1:{self._gw_port}"

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self._http_port}/api/v10"

    def wait_identify(self, timeout: float = 120.0) -> bool:
        return self._identified.wait(timeout=timeout)

    def wait_voice_connected(self, timeout: float = 120.0) -> bool:
        return self._voice_connected.wait(timeout=timeout)


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: FakeDiscordServer) -> None:
        self._server = server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._server.handle_rtp(data, addr)


def _frame_to_s16_mono_48k(frame: Any, arr: Any) -> bytes:
    """A decoded Opus frame → s16 mono 48 kHz PCM, the capture format."""
    import numpy as np

    data = arr
    # PyAV gives float planar (fltp) for Opus; shape (channels, samples).
    if data.dtype != np.int16:
        data = np.clip(data, -1.0, 1.0)
        data = (data * 32767.0).astype(np.int16)
    if data.ndim == 2 and data.shape[0] > 1:
        mono = data.mean(axis=0).astype(np.int16)
    elif data.ndim == 2:
        mono = data[0]
    else:
        mono = data
    pcm = mono.tobytes()
    rate = frame.sample_rate or SAMPLE_RATE
    if rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, SAMPLE_WIDTH, 1, rate, SAMPLE_RATE, None)
    return pcm


def _payload_json_content(raw: bytes) -> str:
    """Extract `content` from the `payload_json` part of a raw multipart body.

    discord.py names the JSON part `payload_json`; find its header, take the
    bytes to the next boundary, and read `content`. Best-effort — a body we
    cannot parse yields no text, never an exception.
    """
    import json as _j

    marker = b'name="payload_json"'
    idx = raw.find(marker)
    if idx == -1:
        return ""
    start = raw.find(b"\r\n\r\n", idx)
    if start == -1:
        return ""
    start += 4
    # The part ends at the next boundary line (`\r\n--`).
    end = raw.find(b"\r\n--", start)
    chunk = raw[start:end] if end != -1 else raw[start:]
    try:
        return str(_j.loads(chunk.decode("utf-8", "replace")).get("content") or "")
    except Exception:  # noqa: BLE001 - not JSON; nothing to tap
        return ""


def _message_object(channel_id: str, content: str) -> dict[str, Any]:
    return {
        "id": str(secrets.randbits(63)),
        "type": 0,
        "channel_id": channel_id,
        "content": content,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "edited_timestamp": None,
        "tts": False,
        "mention_everyone": False,
        "mentions": [],
        "mention_roles": [],
        "attachments": [],
        "embeds": [],
        "pinned": False,
        "author": {
            "id": str(_BOT_USER_ID),
            "username": "colleague-assistant",
            "discriminator": "0001",
            "avatar": None,
            "bot": True,
        },
    }


class DiscordVoiceRoom(SubstrateVoiceRoom):
    """A Discord voice channel as a harness room, capturing hermes's replies.

    Capture is the base class's: an assistant *utterance* is a spoken audio
    segment, and its exact text is the arm's own — taken from the arm's TTS
    input, not its channel. hermes's channel carries a lot besides speech
    (system notices, reasoning it prints but does not say, streaming status),
    so the reliable signal is what it actually voiced. The session taps the
    exact spoken string at the arm's TTS command and hands it to
    `note_assistant_text`; the base pairs it FIFO with the audio segment it
    produced. Channel posts are kept as evidence only.
    """

    substrate = "discord"

    def __init__(
        self,
        *,
        room_name: str,
        bank: VoiceBank,
        assistant_identities: tuple[str, ...],
        personas: list[str],
        transcribe_assistant: bool = True,
    ) -> None:
        super().__init__(
            room_name=room_name,
            bank=bank,
            assistant_identities=assistant_identities,
            transcribe_assistant=transcribe_assistant,
        )
        # An arm greets/acknowledges before the scene; capture starts at arm().
        self._armed = False
        self._encoder: Any = None
        self._raw_posts: list[str] = []
        self.server = FakeDiscordServer(
            personas=personas,
            on_reply=self._raw_posts.append,
            on_bot_pcm=lambda pcm: self._feed_assistant_pcm(
                self.assistant_identity, pcm
            ),
        )

    # -- playback ---------------------------------------------------------

    def _play(self, who: str, pcm: bytes) -> None:
        frames = self._encode_opus(pcm)
        if frames:
            self.server.send_persona_opus(who, frames)

    def _encode_opus(self, pcm: bytes) -> list[bytes]:
        import av

        if self._encoder is None:
            enc = av.CodecContext.create("libopus", "w")
            enc.sample_rate = 48000
            enc.layout = "stereo"
            enc.format = "s16"
            enc.bit_rate = 96000
            enc.open()
            self._encoder = enc
        stereo = audioop.tostereo(pcm, SAMPLE_WIDTH, 1, 1)
        frame_bytes = _OPUS_FRAME_SAMPLES * SAMPLE_WIDTH * 2  # stereo
        frames: list[bytes] = []
        for i in range(0, len(stereo), frame_bytes):
            chunk = stereo[i : i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            frame = av.AudioFrame(
                format="s16", layout="stereo", samples=_OPUS_FRAME_SAMPLES
            )
            frame.sample_rate = 48000
            frame.planes[0].update(chunk)
            for pkt in self._encoder.encode(frame):
                frames.append(bytes(pkt))
        return frames

    # -- interface --------------------------------------------------------

    def invite(self) -> RoomInvite:
        return RoomInvite(
            url=self.server.gateway_url,
            token="",
            identity=self.assistant_identity,
            room_name=self.room_name,
            assistant_identities=self.assistant_identities,
        )

    def evidence(self) -> dict[str, Any]:
        return {**super().evidence(), "channel_posts": list(self._raw_posts)}

    def _shutdown(self) -> None:
        self.server.close()


def write_sitecustomize(path: Any, *, api_base: str, gateway_url: str) -> None:
    """Write the shim that points hermes's discord.py at the fake server.

    `discord.py`'s REST base and gateway URL are class constants, and its one
    hard-`wss://` path (the voice gateway f-string) is rewritten to `ws://`
    on loopback in `HTTPClient.ws_connect`. No hermes code is touched; the
    shim rides in on PYTHONPATH and is imported by `site` at startup.
    """
    from pathlib import Path

    Path(path).write_text(
        f'''"""Harness shim: repoint discord.py at the loopback fixture server."""
import discord.http
import discord.gateway
import yarl

discord.http.Route.BASE = {api_base!r}
discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL({gateway_url!r})

_orig_ws_connect = discord.http.HTTPClient.ws_connect


async def _ws_connect(self, url, *args, **kwargs):
    if url.startswith("wss://127.0.0.1") or url.startswith("wss://localhost"):
        url = "ws://" + url[len("wss://"):]
    return await _orig_ws_connect(self, url, *args, **kwargs)


discord.http.HTTPClient.ws_connect = _ws_connect
''',
        encoding="utf-8",
    )
