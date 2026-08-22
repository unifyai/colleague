# meeting

Several people in a room, one assistant among them. Does it speak when it is
spoken to, stay quiet when two humans are talking to each other, answer
before the moment has passed, and turn a request made in passing into work?

**v0 runs on a text room.** The scenes, the roles, the checks and the
scorer are medium-agnostic; the transport is what changes when the room
becomes a call, and that is the next step, not a redesign.

## The people are role-players, not scripts

Nobody can script every branch of what a model will say to three people, or
ask them, or get wrong. So the people in the room are personas — a brief,
what they know, how they behave — and each scene is a list of **beats**:
what gets said, by whom, in order, and whether it is aimed at the assistant.
That order is the deterministic flow. What varies is the wording (a live
role says its beat in its own words, in the context of what has been said)
and the reactions (a live role may answer a question the assistant puts to
it, or push back). Without a model the roles speak their beats verbatim and
never react — the controlled version of the same scene, which is what the
self-test runs. See `colleague/harness/roleplay.py`.

Ground truth stays in the fixture (`/notes`), scoring reads only what the
fixture witnessed (`/say`, `/schedule`), and timing is recorder sequence:
a beat aimed at the assistant records where it was spoken and where the
next line landed, so "answered before the moment passed" is two integers.
Anything a live role touches is a distribution: run with `--repeat` and
read the spread, not a single verdict.

## Scenes

| Scene | Beats | Checks |
|---|---|---|
| `addressed_by_name` | venue chat; Daniel asks the assistant the deploy window by name; chat continues | answered with the fixture literal (**disclosure control**); nothing said before being addressed; answer landed before the next human line; only one line |
| `humans_talking` | five lines among three people, none aimed at the assistant | zero assistant lines |
| `commanded_work` | Priya asks for the shortlist every Monday at 9; Bob asks the deploy window | a `/schedule` for Priya, weekly, Monday; Bob answered; nothing said before being addressed |
| `interrupted_mid_answer` | Daniel asks the budget, then changes his mind (four seconds' patience) and asks the deploy window | the answer after the change is the deploy window; the abandoned budget answer does not follow it |

DEGRADED is used for the right thing at the wrong moment: answering after
the room moved on, or with extra lines, or finishing the abandoned answer
before giving the new one. `humans_talking` needs `addressed_by_name` beside
it: a silent arm passes one and fails the other.

Every line a role says is delivered to the arm through its own channel —
`interject` while a turn is running, a continuation turn otherwise — and
recorded with how it got there. An arm no second person can reach resolves
to UNSUPPORTED rather than being scored as having said nothing.

## First live runs (2026-08-18)

**`unify-cm`, cloud sweep, live roles, `--repeat 3`** (run 32100545505):

| Scene | Spread | Reading |
|---|---|---|
| `interrupted_mid_answer` | PASS ×3 | after Daniel changed the question: one line, "Thursday at 14:00 UTC, weekly", nothing about the budget — every time |
| `addressed_by_name` | DEGRADED ×3 | the right answer, one line, silent until addressed, but every time slower than the 25 s patience, so two human lines had landed first. Once it also answered Priya's question *to Daniel* ("Yes, please book the Thursday-morning walk-through") — speaking for the boss. The latency is the CM's whole-turn cost on this surface; both are real |
| `humans_talking` | PASS ×1 · FAIL ×2 | when it failed it summarised the humans back to themselves ("Sounds aligned: second week of October, with the platform team attending…") — the same shape prime-agent showed, less often |
| `commanded_work` | (re-read below) | it created the schedule in all three runs and answered Bob in all three; twice it asked Priya the timezone first and she answered "London time, Europe/London" (live role) |

`commanded_work` first scored FAIL ×2 · DEGRADED ×1, and that was the
fixture's fault: twice the arm wrote `cadence: "every Monday at 09:00"` — the
meaning exactly, the enum wrong — the fixture accepted it and the scorer
failed it. A real API rejects a cadence outside its enum and the same arm
self-corrects on the 400 (it visibly did, on a missing-field 400 in the same
run). The fixture now validates `cadence`, and the scorer reads the day from
either field; recorded as `[wrong]`. Re-scored against what the runs did, the
spread is PASS ×2 · DEGRADED ×1 (Bob's answer late once).

Read the whole table as a shape, not a verdict: n = 3, one arm, one week's
code.

**Text room under group semantics** (single run, `unify-cm`, run
`2026-08-19T14-51-35Z-unify-cm-ac83c9`): `interrupted_mid_answer` PASS;
`addressed_by_name` DEGRADED — answered after the conversation had moved
on, the same latency degradation as the spread above; `commanded_work`
FAIL — it asked Priya for the timezone, was told, then declined to
schedule into a scheduler whose `09:00` encodes no timezone
(`answered_bob` and `silent_until_addressed` both held); `humans_talking`
FAIL — one volunteered line, spoken through the room. The room reaches the
CM as group traffic: `group_id` plus the cast's contact ids per line,
mentions left empty so noticing your own name stays the thing measured;
room-addressed sends bridge to `/say`.

**`unify-cm`, local, live roles, `--transport voice --only addressed_by_name
--repeat 5`** (2026-08-19, runs `13-42-42Z`/`13-46-33Z`/`13-52-24Z`/
`13-59-10Z`/`14-06-51Z`):

| Scene | Spread | Reading |
|---|---|---|
| `addressed_by_name` (voice) | DEGRADED ×4 · 1 discarded | the right answer in every valid run — "Thursday at fourteen o'clock UTC" — always as a fast-brain defer line first, then the answer. Three landed after the room had moved on; one was in time but with extra lines, the live roles' reactions pulling it into over-talking (it volunteered venue opinions and the budget, unasked). The fifth run is discarded as a harness fault, not scored: the bridge's stale-dispatch delete raced a slow worker boot and seated three agents in one room — a chorus the harness caused (fixed: a dispatch with a job assigned is never deleted) |

Scored on the assistant's utterance text; "fourteen o'clock" counts as
`14:00` (spoken forms, declared beside the fixture's ground truth).
Correction, on the record (2026-08-20): these runs' "arm-exact" lines were
in fact Deepgram transcripts — the bridge's utterance tap parsed the arm's
events flat when they serialize nested, and fell back silently. The
verdicts survive (the credited checks found their markers in text that
carried them; the lost ones were about speaking at all or speaking late,
which transcription cannot manufacture), the tap is fixed for future runs,
and the trail is in SCENARIO_CHANGES ("The callee"). Same day, earlier:
three runs excluded as environment faults
(the agent linked to the harness recorder; missing turn-detector models;
Orchestra without its embed key) — the trail is in SCENARIO_CHANGES. The
defer-then-answer shape means `only_one_line` is structurally out of reach
for this surface at this model pin; the whole-turn latency is the same cost
the text `--repeat 3` showed, now in real seconds.

**`unify-cm`, local, live roles, `--transport voice`, first full-track
pass** (run `2026-08-19T14-23-55Z-unify-cm-39a77c`, n = 1 — a shape, not a
verdict):

| Scene | Result | Reading |
|---|---|---|
| `addressed_by_name` | DEGRADED | right answer, late — the standing signature |
| `humans_talking` | FAIL | spoke when nobody asked: summarised the humans back to themselves, the same shape as its text runs and prime-agent's |
| `commanded_work` | FAIL | neither the Monday schedule nor Bob's answer landed — two aimed asks in one live scene is where the whole-turn cost compounds |
| `interrupted_mid_answer` | PASS | dropped the abandoned budget question and answered the new one, over audio |
| `answered_in_time` | FAIL | got the answer out but spoke before being addressed and in several lines; the 8-second patience is exactly what the defer shape cannot make |
| `two_assistants` | UNSUPPORTED | the bridge fields one CM instance per call, by design — the floor protocol goes unmeasured rather than falsely kept |

**`hermes-voice`, local, live roles, `--transport voice`, first full-track
pass** (2026-08-20, n = 1 — a shape, not a verdict). hermes joins a **Discord
voice channel** the harness serves on loopback (a Discord-protocol server the
real `hermes gateway` connects to): the personas are separate Discord users,
each on its own SSRC, and hermes attributes them by voice op-5, transcribes
with its local Whisper, and speaks Opus back. Its words are its own, tapped at
its TTS input.

| Scene | Result | Reading |
|---|---|---|
| `addressed_by_name` | PASS | one line, "Thursday, at two P. M. UTC", silent until addressed and in time — where the CM's whole-turn latency ran DEGRADED, hermes answered at chat speed |
| `humans_talking` | FAIL | given five lines nobody aimed at it, it joined in — asked the humans questions and summarised them back; the recurring shape across every arm |
| `commanded_work` | DEGRADED | the Monday schedule correct (weekly, Monday, to Priya) and Bob answered, but after the room had moved on |
| `interrupted_mid_answer` | PASS | dropped the abandoned budget and answered the deploy window, over audio |
| `answered_in_time` | FAIL | the answer was there ("Thursday at 14:00 UTC — that's 3 PM British Summer") but it spoke before being addressed and in several lines; the 8-second patience is what the over-talk cannot make |
| `two_assistants` | UNSUPPORTED | one Discord bot per call, by design |

The recurring loss is the mechanism under test — whether to speak now among
several humans, for which hermes has no arbiter, so it engages with cross-talk
(in one run it TTS-spoke its own stage directions aloud, "Hermes stays quiet
to let Priya answer"). Scored on the arm's own utterance text; "two P. M." is
`14:00` said aloud (a TTS text-normalizer spells the p.m. form out with
periods), declared beside the fixture's ground truth.

**`openclaw-voice`, local, live roles, `--transport voice`, first full-track
pass** (2026-08-20, n = 1 — a shape, not a verdict). OpenClaw fields an
**inbound phone call** the harness plays the carrier for (a Twilio-shaped
webhook and media stream on loopback): its own Deepgram STT hears the call,
each caller turn drives a full agent turn pinned to the bench model, and it
speaks its own TTS back down the µ-law stream. Its words are its own, tapped
at its TTS input.

| Scene | Result | Reading |
|---|---|---|
| `addressed_by_name` | FAIL | answered correctly ("Thursday at two p.m. UTC, which is three p.m. London") but over-talked the venue chat first and in several lines. An isolated repeat ran DEGRADED — right answer, late, silent until addressed — so read it as a distribution |
| `humans_talking` | FAIL | joined the humans' cross-talk, the same shape as every other arm |
| `commanded_work` | FAIL | answered Bob and stayed silent until addressed, but never created the Monday schedule — on a call it did not reach for the `/schedule` reference API |
| `interrupted_mid_answer` | PASS | one line, dropped the abandoned budget, gave the deploy window |
| `answered_in_time` | FAIL | the answer was there ("Thursday at 2 p.m. UTC") but not in one line and not silent first |
| `two_assistants` | UNSUPPORTED | one call, one assistant per bridge |

The standing signature is whole-turn latency: an inbound voice response is a
full embedded agent turn (tens of seconds), so the harness holds the call open
a drain after the scene to capture the arm's audio rather than score a
correct-but-late answer as silence — even so it answers late and over-talks.
It renders `14:00` as "2 p.m. UTC / 3 p.m. London", both spoken, so the UTC
form is what the scorer reads.

Both voice passes carry `transport: voice` and are never merged with a text
cell; `results/` holds the runs (a CI artifact, gitignored — these tables are
the committed record).

**`openclaw-gateway`, local, live roles, `--repeat 3`:**

| Scene | Spread | Reading |
|---|---|---|
| `addressed_by_name` | PASS ×3 | one line, the fixture literal, inside the room's patience every time — a live Gateway session answers at chat speed, where the CM's whole-turn latency ran DEGRADED |
| `humans_talking` | PASS ×1 · FAIL ×2 | the same failure shape as unify-cm and prime-agent: given five lines nobody aimed at it, it summarised the humans back to themselves ("I'm caught up. I have the venue shortlist…") |
| `commanded_work` | PASS ×3 | the schedule correct every time — `weekly`, Monday, to Priya — and Bob answered in time. These runs predate the cadence 400; every schedule it wrote was already inside the enum, so the fixture change reads the same either way |
| `interrupted_mid_answer` | PASS ×3 | the answer after Daniel's change is the deploy window; the abandoned budget answer never followed |

The one recurring loss is the mechanism under test: whether to speak now
among several humans. The Gateway arm reads room lines as `[name] message`
turns on one session — sender identity is text, as the profile says — and
twice in three runs it broke silence to be helpful.

**`prime-agent`** (print mode, n = 1 — an old-regime run of a retired arm;
the arm is now `prime-agent-rpc`, whose steering lane changes exactly the
mechanism these losses hinge on): DEGRADED · FAIL · DEGRADED · PASS.
Every line reached it as a later turn — print mode has no live channel — so
"after the room moved on" is true by construction and the reasons say so;
the same DEGRADED `interruption` gives a queued correction. `humans_talking`
is genuine: given five lines nobody addressed to it, it narrated them back
to the room. The live roles behaved as designed: Daniel re-asked when no
answer came, Priya answered the assistant's paraphrase.

## What to expect, and the fair reading

The comparison harnesses are not empty here. hermes joins Discord voice with
per-speaker attribution and has a Google Meet plugin; OpenClaw has Talk mode
and Meet/Zoom/Teams extensions, and in text rooms both gate on mention or a
`NO_REPLY`-style token. unify's fast brain runs a structured
`silence | defer | smalltalk | continuation | hang_up` decision every turn
with a group-call block at two or more other participants, plus
`ProactiveSpeech` and a `MeetFloor` protocol between assistants. What none
of the three has is an arbiter for *whether to speak now* among several
humans; that is the mechanism under test, and it has no live multi-human
evaluation in unify's own suite.

**Adapter note, `unify-cm`.** Room lines arrive today as direct messages
from each named contact, with the room stated in the context; the CM's own
room semantics (`group_id`, `mentions` on `UnifyMessageReceived`) are not
yet wired in the adapter, so the arm reasons about the room from the words
rather than from structure. Wire `group_id` before reading a unify result
here as the product's room behaviour.

## Voice — the transport, per substrate

The scenes do not change; the transport does, and each capable arm now runs
over the room its product actually ships:

- **`unify-cm`** — LiveKit, because `unify_meet` *is* a LiveKit room and its
  fast brain already speaks it (`arms/sessions/unify_cm_voice.py`).
- **`hermes-voice`** — a **Discord voice channel** the harness serves on
  loopback (`harness/voice/discord_room.py`): a Discord-protocol server (REST,
  gateway WS, voice WS, UDP media, faithful to discord.py 2.7.1) the real
  `hermes gateway` connects to. Nothing in hermes is patched; a `sitecustomize`
  shim repoints its REST base and gateway URL and rewrites the one wss://-only
  path to ws:// on loopback.
- **`openclaw-voice`** — an **inbound phone call** the harness plays the
  carrier for (`harness/voice/phone_room.py`): a Twilio-shaped webhook and
  media stream on loopback into OpenClaw's voice-call extension, G.711 µ-law
  both ways, no provider account.

The invariants hold across all three (the contract is `harness/voice/README.md`
§"Why LiveKit…"): the arm joins its own substrate's room with its own identity;
the harness owns the persona voices (separate speakers, so attribution is a
real problem) and the capture; the assistant's words are the arm's own, taken
where it speaks from text — for every arm, the exact string it fed its TTS,
never a harness-supplied audio path (the capability under test). A non-LiveKit
substrate implements only how audio moves, over the shared
`harness/voice/substrate.py`.

What not to measure here: barge-in latency in milliseconds, disfluency,
prosody. The purpose-built rigs measure those better and would invite the
comparison.

## Human protocol

Run `python -m colleague.run meeting --arm human --repeat 5`. Role-played lines
arrive live with named speakers. The same floor, timing, interruption and
scheduled-work checks apply. Repeats remain required, and active labour/cost is
reported separately from role-player cost.

## The persona boundary

Scenes stay scripted stimulus — beats in order, worded live in character —
exactly as before. What the persona engine adds is reactivity after the
scene: a direct question the arm sends to a named participant gets that
person's labelled reply back as inbound traffic, and scene-wording prompts
stay out of persona memory (they are direction, not conversation).
