"""What each arm can and cannot express, declared up front.

Several tracks probe capabilities that some harnesses simply do not have. A
harness with no running loop cannot receive a mid-task correction; a harness
with one flat memory directory cannot scope a fact to a subset of readers.
Recording those as a score of zero would be dishonest — zero is what you get
for trying and failing, and these arms are not trying.

So an arm declares its mechanisms, and a scenario that needs a mechanism the
arm lacks resolves to ``UNSUPPORTED``. That is reported as its own column,
never averaged into an accuracy figure, and never presented as a loss. The
`standing` track already did this by hand for OpenCode's policy propagation
("not reachable"); this makes it a first-class outcome instead.

The distinction that matters in reporting:

    PASS         the arm did the right thing
    FAIL         the arm had the mechanism and still got it wrong
    UNSUPPORTED  the arm has no mechanism for this at all
    DEGRADED     the arm reached the outcome through a materially worse
                 route (a restart rather than a redirect, say) — correct,
                 but the cost belongs in the write-up
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"

    ERROR = "error"
    """The harness could not measure — a bad credential, a crash, a timeout.

    Distinct from FAIL, which means the arm had its chance and got it wrong.
    Collapsing the two lets a broken sweep read as a arm that performed
    badly, which is the most expensive kind of wrong answer a benchmark can
    give: it looks like a finding. An ERROR anywhere fails the run.
    """

    INVALID = "invalid"
    """The environment corrupted the measurement — a persona leaked content
    its track forbids (the move a check measures, a control's undiscoverable
    spec). The cell is void: not a PASS the leak gifted, not a FAIL the arm
    never earned, and never in an accuracy denominator. Repeats provide
    replacement samples; the summary reports the void and why.
    """

    @property
    def scoreable(self) -> bool:
        """Whether this outcome belongs in an accuracy denominator."""
        return self in (Outcome.PASS, Outcome.FAIL, Outcome.DEGRADED)

    @property
    def credited(self) -> bool:
        """Whether this outcome counts as the scenario having been achieved."""
        return self in (Outcome.PASS, Outcome.DEGRADED)


class Steering(str, Enum):
    """How a correction can reach work that is already running."""

    LIVE_INTERJECT = "live_interject"
    """The running loop accepts a message mid-flight and adapts in place."""

    QUEUED_FOLLOWUP = "queued_followup"
    """The correction is delivered as a new turn once the current one ends."""

    RESTART_ONLY = "restart_only"
    """The only way to change course is to abandon the run and start over."""

    NONE = "none"
    """No mechanism at all: the work runs to completion unobserved."""


class Storage(str, Enum):
    """How learned knowledge can be scoped once it is written down."""

    SCOPED = "scoped"
    """Facts can be filed where only some readers can reach them."""

    FLAT = "flat"
    """One store; anything written is readable by anyone who runs the agent."""

    NONE = "none"


@dataclass(frozen=True)
class ArmProfile:
    """The mechanisms an arm brings to the multi-party tracks.

    These are properties of the harness, not of the model. They are declared
    here rather than discovered at runtime so that a scenario can decide
    up front whether it is even applicable, and so a reader can check the
    claim against the arm's own documentation.
    """

    name: str
    steering: Steering
    storage: Storage
    persistent_sessions: bool
    """Whether a finished task can be resumed with its working state intact."""

    multi_party: bool
    """Whether the harness models more than one human correspondent."""

    clarification: bool
    """Whether the harness can ask the user a question and *block* on it.

    The distinction that matters is blocking. Any arm can emit a question;
    the capability is suspending the work until an answer arrives, so the
    task resumes with it rather than proceeding on a guess.

    A fixture must never provide this. An earlier version of `inheritance`
    exposed a `/clarify` HTTP endpoint, which handed a fake mechanism to arms
    that have none and steered the one arm that has a real one away from it —
    a task description that names an endpoint gets that endpoint called from
    code, and code cannot wait for a person. It measured who used the stub.
    """

    accepts_images: bool
    """Whether image content can reach the arm through its normal input path."""

    scheduler: bool
    voice: bool = False
    """Whether the arm can join a room as an audio participant — its own
    identity, listening to the room's audio, speaking through its own voice
    surface. Never satisfied by a harness-supplied audio path: a "say this
    text and we'll voice it" endpoint is the capability under test being
    faked, exactly as the old `/clarify` stub was. The notes name the
    surface (and, where every surface an arm has binds to a third-party
    service the methodology excludes, they say that), so a reader can check
    the claim.
    """

    notes: str = ""

    def supports(self, requirement: str) -> bool:
        return bool(getattr(self, requirement, False))


#: Declared from each harness's own documented capabilities. Where a claim is
#: contestable it is stated in ``notes`` so a reader can check it rather than
#: take it on trust.
PROFILES: dict[str, ArmProfile] = {
    "hermes-tui": ArmProfile(
        name="hermes-tui",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=False,
        scheduler=True,
        notes=(
            "The TUI gateway JSON-RPC surface (`python -m tui_gateway.entry`),"
            " documented by hermes as a public integration protocol. "
            "prompt.submit returns at status=streaming; session.steer injects "
            "into the running tool batch and session.redirect replaces the "
            "in-flight model call; clarify.request/clarify.respond is a real "
            "blocking question channel; session.resume/branch continue the "
            "same SQLite sessions the CLI writes. Senders are still text in "
            "one session — multi-person identity is a messaging-gateway "
            "capability this surface does not carry. Voice: hermes's real "
            "voice surfaces (Discord voice, the Meet plugin) do not reach "
            "this text surface; the Discord substrate is its own arm, "
            "`hermes-voice`."
        ),
    ),
    "openclaw-gateway": ArmProfile(
        name="openclaw-gateway",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=True,
        scheduler=True,
        notes=(
            "OpenClaw's Gateway WebSocket protocol (docs/gateway/protocol.md), "
            "the control plane every product client speaks, driven from a "
            "stdlib client against a private managed Gateway with its own "
            "state dir and config. chat.send acks before the model call and "
            "the reply is the run's terminal `chat` event; a correction is "
            "chat.send with queueMode=steer bound to the active run — the "
            "product's default queue mode, drained at the next model or "
            "tool-launch boundary, never a restart (queue-steering.md); the "
            "blocking `ask_user` tool surfaces as a `question.requested` event "
            "and is answered with `question.resolve`, the method the Control "
            "UI and channels use (docs/tools/ask-user.md); images travel as "
            "chat.send attachments. multi_party stays false because a sender "
            "the model can see is a *channel* envelope in OpenClaw — the "
            "Gateway chat surface 'does not split messages by sender' and "
            "attributes turns best-effort (docs/concepts/multi-user.md) — so "
            "senders reach this arm as text, as they reach hermes-tui. "
            "Voice: the product has Talk mode (vendor apps), Meet/Zoom/Teams "
            "meeting extensions and a voice-call extension "
            "(Twilio/Telnyx/Plivo) — every surface binds to a vendor app or "
            "a third-party service, and nothing on the Gateway chat surface "
            "joins a room, so voice scenarios resolve UNSUPPORTED here; the "
            "voice-call extension driven over a harness-played carrier is "
            "its own arm, `openclaw-voice`."
        ),
    ),
    "prime-agent-rpc": ArmProfile(
        name="prime-agent-rpc",
        clarification=False,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=True,
        scheduler=True,
        notes=(
            "prime-agent's JSONL-RPC mode (`--mode rpc`, docs/rpc.md), the "
            "documented headless integration surface: one long-lived process "
            "per session, a custom provider in a throwaway agent dir pointed "
            "at the recording proxy, and a run-local session dir. `prompt` "
            "acks on acceptance and the turn ends at `agent_end`; a "
            "correction is the `steer` command — the steering lane of "
            "session-action-store.ts, delivery policy next_turn_boundary: "
            "delivered after the current assistant turn's tool calls, before "
            "the next model call, never an abort. Follow-ups queue on the "
            "follow-up lane (when_run_idle). Images travel on the prompt. "
            "No ask-the-user tool exists anywhere in the product (the only "
            "tools are bash/edit/ipython; `side-question` runs the other "
            "way), so clarification stays false rather than faked; senders "
            "are text in one session — terminal-only, single-user. Voice: "
            "none on any surface, so voice scenarios resolve UNSUPPORTED. "
            "Scheduler: cron/interval/once plus heartbeat, every firing a "
            "prompt into an agent turn — no script payload, no zero-token "
            "firing. Memory: `kind: memory` entries in the versioned harness "
            "store, no retrieval index. Distinctive: Python skills "
            "pre-imported into a persistent IPython kernel, versioned "
            "HarnessEntry with a refinements.jsonl audit."
        ),
    ),
    "unify-cm": ArmProfile(
        name="unify-cm",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.SCOPED,
        persistent_sessions=True,
        multi_party=True,
        accepts_images=True,
        scheduler=True,
        voice=True,
        notes=(
            "The ConversationManager — the door a person talks to unify "
            "through, and therefore the harness's one arm. Senders are "
            "first-class contacts on every inbound event; replies are Sent "
            "events addressed to a contact; silence is the `wait` tool, "
            "detected exactly; each in-flight action exposes its own "
            "interject/stop/ask tools and routing a correction to the right "
            "one is a recorded brain decision. "
            "Clarification is the product's own channel, not a synthetic "
            "tool: a question the brain sends to a cast contact is answered "
            "by that persona, as an inbound message on the CM's own path, "
            "and the `who` on each round is scorer-readable — verified live "
            "by inheritance/cold_control (asked Daniel, acted on the "
            "answer). The bridge only relays; whether the brain asks at "
            "all, and whom, stays the measured behaviour. Voice: "
            "`unify_meet` is the product's own LiveKit room; the fast brain "
            "(medium_scripts/call.py) joins it as a participant, decides "
            "silence|defer|smalltalk|continuation|hang_up per turn, and "
            "speaks from text the adapter captures exactly "
            "(app:comms:unify_meet_utterance)."
        ),
    ),
    "opencode": ArmProfile(
        name="opencode",
        clarification=False,
        steering=Steering.RESTART_ONLY,
        storage=Storage.FLAT,
        persistent_sessions=False,
        multi_party=False,
        accepts_images=True,
        scheduler=False,
        notes=(
            "`opencode run` is one-shot. Workspace files persist between "
            "runs, but no running loop can be addressed."
        ),
    ),
    "hermes-voice": ArmProfile(
        name="hermes-voice",
        clarification=False,
        steering=Steering.RESTART_ONLY,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=True,
        accepts_images=False,
        scheduler=True,
        voice=True,
        notes=(
            "hermes's Discord voice substrate, driven for real: the harness "
            "stands up a Discord-protocol server on loopback "
            "(harness/voice/discord_room.py) and runs the pinned `hermes "
            "gateway` against it. The arm joins a guild voice channel through "
            "its own discord.py client, attributes each speaker by SSRC "
            "(voice op 5), transcribes with its local Whisper (stt.provider "
            "local, offline), and speaks replies as Opus. Personas are "
            "separate Discord users each on their own SSRC, so who-said-what "
            "is a real problem the arm solves from the audio. Utterance text "
            "is the arm's own, tapped at its TTS input — the exact string it "
            "chose to say at the point it speaks from text, the same faithful "
            "capture unify-cm's LiveKit result uses, never a transcription of "
            "the audio (a TTS voice's clause pauses would fragment that). The "
            "bot audio is carried on the real substrate and captured as "
            "corroboration (duration, and a whole-call cross-check "
            "transcript). No hermes code is patched: discord.py's REST base "
            "and gateway URL are class constants a sitecustomize shim on "
            "PYTHONPATH repoints at the loopback server, and its one wss://-"
            "only path (the voice gateway) is rewritten to ws:// on loopback. "
            "Two assistants on one call is Unsupported by design — the bridge "
            "fields one bot per call. This is the voice transport of the "
            "same harness the text `hermes-tui` arm drives; results carry "
            "transport=voice and are never merged with a text cell."
        ),
    ),
    "openclaw-voice": ArmProfile(
        name="openclaw-voice",
        clarification=False,
        steering=Steering.RESTART_ONLY,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=True,
        scheduler=True,
        voice=True,
        notes=(
            "OpenClaw's voice-call extension, driven for real over an inbound "
            "phone call: the harness plays the carrier "
            "(harness/voice/phone_room.py), POSTing the provider's inbound "
            "webhook to the extension's local server and connecting the "
            "Twilio-shaped media stream it answers with, then streaming G.711 "
            "µ-law both ways. The extension runs its own classic streaming "
            "pipeline — its own TTS into the stream, its own Deepgram STT out "
            "of it — and each caller turn drives a full agent turn "
            "(response-generator), pinned to the bench model via "
            "voice-call.responseModel. Personas are distinct TTS voices on the "
            "one caller channel (a conference call over one line — speaker "
            "attribution from the audio is the arm's problem). Utterance text "
            "is the arm's own, tapped at its TTS input (the exact spoken "
            "string, the same capture as unify-cm and hermes-voice); the "
            "streamed µ-law audio is captured as corroboration, with a "
            "whole-call transcript kept as a cross-check. The call is ended by "
            "the carrier's own "
            "`completed` webhook, never the arm's hangup (which would POST to "
            "the real carrier API). No provider account: provider `twilio` "
            "with skipSignatureVerification and a fake public host; every "
            "byte on the carrier side is the harness. The voice transport of "
            "the same harness the text `openclaw-gateway` arm drives; "
            "results carry transport=voice."
        ),
    ),
}


@dataclass
class ScenarioResult:
    """One scenario's outcome for one arm."""

    scenario: str
    outcome: Outcome
    detail: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome.value,
            "reason": self.reason,
            **({"detail": self.detail} if self.detail else {}),
        }


def summarize(results: list[ScenarioResult]) -> dict[str, Any]:
    """Aggregate, keeping UNSUPPORTED out of the accuracy denominator."""
    scoreable = [r for r in results if r.outcome.scoreable]
    credited = [r for r in scoreable if r.outcome.credited]
    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r.outcome.value] = by_outcome.get(r.outcome.value, 0) + 1
    return {
        "total_scenarios": len(results),
        "scoreable": len(scoreable),
        "credited": len(credited),
        "accuracy": (round(len(credited) / len(scoreable), 4) if scoreable else None),
        "by_outcome": by_outcome,
        "results": [r.as_dict() for r in results],
    }
