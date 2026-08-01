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
        "hermes": "colleague.arms.sessions.hermes_session",
        "openclaw": "colleague.arms.sessions.openclaw_session",
        "opencode": "colleague.arms.sessions.opencode_session",
        "mock": "colleague.arms.sessions.mock_session",
    }.get(name)
    if module:
        importlib.import_module(module)


ARMS = ("unify", "hermes", "openclaw", "opencode")
