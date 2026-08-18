# The voice transport

`meeting` was built as a text room with one instruction repeated in its own
files: the scenes, roles, checks and scorer are **medium-agnostic**, and
voice is a *transport swap, not a redesign*. This is that swap. Nothing in
`meeting/scenario.py` changes shape; a scene plays through audio tracks
instead of `interject` calls, and the same journal is scored.

This note is the contract. It is committed before the code so the split of
responsibilities is a decision on the record, not an artifact of whatever was
easiest to build.

## What the harness owns, and what the arm owns

The one rule that shapes everything (DESIGN.md §Non-negotiable rules, and the
`/clarify` post-mortem in SCENARIO_CHANGES): **a fixture must never supply the
capability the track exists to measure.** `meeting` and `callflow` exist to
measure whether the *agent* joins a room and decides when to speak. So the
arm must join and speak through **its own** voice surface; the harness must
never offer a "say this text and we'll voice it for you" endpoint for the
arm. The equivalent of the `/clarify` stub here would be a harness `/say`
that an arm POSTs lines to — that is exactly what the text room does, and it
is why the text room can only ever be *v0*.

The split:

| The harness owns | The arm owns |
|---|---|
| The room (a LiveKit room it creates and holds) | Joining the room as a participant with its own identity |
| Each **person's** voice — one TTS-rendered audio track per persona | Listening to the room's audio |
| Capture: every participant's utterance start/end, and the assistant's audio | Deciding whether to speak, and speaking (its own TTS) |
| Timestamps into the fixture recorder, so scoring is unchanged | — |

The persona voices are the *environment*. The assistant's voice is the
*system under test*. The harness renders the first and only ever listens to
the second.

## How a `Beat` and a `Scene` become audio

`harness/roleplay.py` is unchanged and stays the source of the flow. A
`Scene` is still an ordered list of `Beat`s; the order is still the
deterministic flow; a live role still rewords in character and may react.
The only difference is the delivery channel:

- **Text room (v0):** a beat aimed at the assistant reaches it through
  `RunHandle.interject(text, sender=)`; the assistant "speaks" by POSTing to
  the fixture's `/say`; both are recorded on the fixture recorder and the
  `seq` on each `Said` is the recorder sequence.
- **Voice room:** a beat is **spoken** through that role's TTS track at the
  same waypoint (the room must have been quiet for `quiet_s`, exactly as in
  text). The assistant "speaks" by emitting audio; the harness captures the
  text of that audio (below) and records it as a `say` entry, so the fixture
  recorder still witnesses every line and `Said.seq` still comes from it.

Two transport timestamps are added to each `Said` and each captured
assistant line, read from the room, never from wall-clock guesses:

- `spoken_at` — when the audio for this line began playing / was first heard.
- `ended_at` — when it finished.

`seq` remains the ordering authority (it is what the scorer reads: "answered
before the next human line" is `answer.seq < next_beat.seq`). The timestamps
are what make *in-time* and *overlap* real measurements rather than proxies
(below), and they are what a voice write-up reports.

## How the assistant's utterance text is obtained, per arm

The scorer's disclosure checks are containment tests on the assistant's
**utterance text** (`"Thursday 14:00 UTC"` appears, the budget marker does
not). Voice does not change that; it changes where the text comes from, and
the rule is: **take it from the arm wherever the arm speaks from text.**

- **unify-cm** speaks by feeding a string to its TTS (the fast/slow-brain
  line). The adapter taps that exact string from the arm's own
  `*_utterance` event — the text the arm chose to say, before it became
  audio. No transcription, no loss. This is the faithful capture and the one
  the primary result uses.
- **An arm that only exposes audio** (a bot that speaks but hands the harness
  no text) is transcribed by a **declared** transcription model (Deepgram
  `nova-3`), and the transcript is committed with the run so a reader can
  check what the scorer read. Declared because a transcription model is a
  second model in the loop, and its identity belongs in the record the same
  way the persona model's does.

Both are recorded as `say` entries with `spoken_at`/`ended_at`. Where both
are available (unify-cm), the exact text is scored and the transcript is kept
alongside as a cross-check.

## In-time and overlap as timestamps

- **In time.** A call tolerates a much shorter pause than a chat thread. The
  `answered_in_time` scene shrinks `patience` to a few seconds — the
  persona's *next line* is the deadline, exactly as in text (`answer.seq <
  next_beat.seq`), but now the seconds between them are real seconds a person
  waited, read from `spoken_at`. "Answered before the moment passed" is the
  same two integers; the write-up can additionally report the wall gap.
- **Overlap.** Two people talking at once is a first-class thing audio can
  show and text cannot. Each participant's utterance carries
  `[spoken_at, ended_at]`; two intervals that intersect are an overlap. The
  `two_assistants` scene scores *no overlap of assistant audio* — at most one
  assistant speaks to a question addressed to "the assistants" — which is a
  pair of intervals that must not intersect. This is the only new measurement
  voice adds to the scorer, and it is a timestamp comparison, not a judgement.

## What is deliberately NOT measured here

The purpose-built rigs own these and would win; measuring them here would
invite the comparison and lose it (DESIGN.md, "What already exists
elsewhere"):

- **Barge-in latency in milliseconds** — τ-Voice / Full-Duplex-Bench.
- **Disfluency, filler, prosody, naturalness** — same.
- **Turn-detection accuracy as a signal-processing problem** — EchoChain.

`meeting` scores *outcomes*: spoke when addressed (fixture literal in the
utterance text), silent while humans talk to each other (zero assistant
utterances in the window), answered before the next human line (two
sequences), no two assistants over each other (two intervals). Every one is
an outcome an audio transport lets us observe more honestly than text, and
none is a quality judgement.

## Why LiveKit, and what a non-LiveKit arm would need

LiveKit is the pragmatic choice, not a requirement of the design:

- unify's own multi-party room (`unify_meet`) *is* a LiveKit room and its
  fast brain already speaks it, so a unify-cm result over LiveKit is the
  product's real room behaviour rather than an adapter approximation.
- It runs fully locally (`livekit-server --dev`), so the controlled path
  needs no third-party account — the same discipline as the fixture servers.
- Its SDK gives per-participant audio tracks and track-level start/end
  events, which is what makes speaker attribution a real problem rather than
  a courtesy: each persona is a **separate track with its own identity**, and
  an arm that wants to know who said what has to do the work.

The transport is behind a small interface (`Room`: create, mint a join token
for an identity, add a persona speaker, capture a participant). An arm on a
different substrate — hermes's Discord voice, a Google Meet bot — joins that
substrate's room; the harness still owns the personas' voices and the
capture on that substrate. What a non-LiveKit arm needs is stated where its
adapter lives: a room the arm can be *invited to* with its own identity, the
personas rendered as separate speakers in it, and a tap on the assistant's
utterance text. The `Room` abstraction is LiveKit today because that is what
one arm's product uses and what runs locally; it is not load-bearing on the
scorer.

## Offline / controlled path (why `selftest` stays green)

`python -m colleague.selftest` runs with no model, no LiveKit, no TTS
credentials, and must stay green. So voice is **opt-in** and **degrades
loudly**:

- The transport is selected per run (`--transport voice`, or `auto`). With
  no transport asked for, `meeting` runs the text room exactly as before —
  which is the path `selftest` takes, so its behaviour is unchanged.
- When voice is asked for but a prerequisite is missing (no
  `livekit-server`, no `LIVEKIT_*`, no TTS key, `livekit` not importable),
  the run does **not** silently fall back and pretend it was voice. It falls
  back to the text room and records the reason on the run
  (`transport: "text (voice unavailable: <reason>)"`), so a text result is
  never read as a voice result.
- The `livekit` import is lazy and confined to this package, so the
  stdlib-only checkout and `selftest` never import it. `colleague`'s
  `pyproject` stays `dependencies = []`; voice is a capability of the
  environment the unify arm already runs in (its venv carries the SDK and the
  keys), declared and checkable, not a new hard dependency of the benchmark.

## The `transport` field

Every run record and every merged result carries `transport` (`text` /
`voice` / `text (voice unavailable: …)`). Text-room and voice results are
**never merged silently** — a `meeting` cell in the aggregate says which
transport produced it. Averaging a voice DEGRADED (whole-turn latency on a
real call) with a text PASS would be a category error, and the field is what
prevents it.
