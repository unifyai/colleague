"""Per-harness session adapters, one per arm, shared by every track."""

from __future__ import annotations

from typing import Callable

from colleague.harness.session import ArmSession

_REGISTRY: dict[str, Callable[..., ArmSession]] = {}


def register(name: str, factory: Callable[..., ArmSession]) -> None:
    _REGISTRY[name] = factory


def build(name: str, **kwargs) -> ArmSession:
    if name not in _REGISTRY:
        _load(name)
    if name not in _REGISTRY:
        raise KeyError(f"unknown arm {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def _load(name: str) -> None:
    """Import on demand: the unify arm pulls in the whole runtime."""
    import importlib

    module = {
        "unify-cm": "colleague.arms.sessions.unify_cm_session",
        "hermes-tui": "colleague.arms.sessions.hermes_tui_session",
        "hermes-voice": "colleague.arms.sessions.hermes_voice_session",
        "openclaw-gateway": "colleague.arms.sessions.openclaw_gateway_session",
        "openclaw-voice": "colleague.arms.sessions.openclaw_voice_session",
        "opencode": "colleague.arms.sessions.opencode_session",
        "prime-agent-rpc": "colleague.arms.sessions.prime_agent_rpc_session",
        "human": "colleague.arms.sessions.human_session",
        "mock": "colleague.arms.sessions.mock_session",
    }.get(name)
    if module:
        importlib.import_module(module)


#: The benchmark interfaces with every harness as though it were a person —
#: English in, English out — so each harness gets exactly one arm: the
#: surface closest to talking to it. That is the persistent conversation
#: layer where the product has one (`unify-cm` = ConversationManager,
#: `hermes-tui` = the TUI gateway JSON-RPC protocol, `openclaw-gateway` =
#: the Gateway WebSocket control plane, `prime-agent-rpc` = JSONL-RPC mode)
#: and the plain CLI where it does not (`opencode`). The voice arms are the
#: same surfaces reached over audio, recorded as transport=voice and never
#: merged with a text cell. The earlier "v0" arms (bare `CodeActActor.act`,
#: one-shot CLIs) were modes of driving a harness, and modes cannot be
#: applied to a person; they are gone, and results produced under them are
#: labelled old-regime wherever they are kept.
AUTOMATED_ARMS = (
    "unify-cm",
    "hermes-tui",
    "hermes-voice",
    "openclaw-gateway",
    "openclaw-voice",
    "opencode",
    "prime-agent-rpc",
)

# Human runs require an attached participant and must never be expanded by
# an unattended ``--arms all`` cloud sweep. They remain ordinary explicit
# arm choices everywhere else.
HUMAN_ARMS = ("human",)
ARMS = (*AUTOMATED_ARMS, *HUMAN_ARMS)
