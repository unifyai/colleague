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
        "unify": "colleague.arms.sessions.unify_session",
        "unify-cm": "colleague.arms.sessions.unify_cm_session",
        "hermes": "colleague.arms.sessions.hermes_session",
        "hermes-tui": "colleague.arms.sessions.hermes_tui_session",
        "openclaw": "colleague.arms.sessions.openclaw_session",
        "opencode": "colleague.arms.sessions.opencode_session",
        "prime-agent": "colleague.arms.sessions.prime_agent_session",
        "mock": "colleague.arms.sessions.mock_session",
    }.get(name)
    if module:
        importlib.import_module(module)


#: `hermes-tui` and `unify-cm` are the faithful surfaces (product steering,
#: clarification, identity); `hermes` and `unify` remain the v0 arms the
#: published standing numbers used. Capability labels name a path.
ARMS = (
    "unify",
    "unify-cm",
    "hermes",
    "hermes-tui",
    "openclaw",
    "opencode",
    "prime-agent",
)
