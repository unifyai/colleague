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

## First live run (n = 1, 2026-08-18, `prime-agent`, print mode)

DEGRADED · FAIL · DEGRADED · PASS. Two things in it are about the arm's
surface and one is about the arm. Every line reached prime-agent as a later
turn — print mode has no live channel — so "answered after the room moved
on" is true by construction and the reasons say so; that is the same
DEGRADED `interruption` gives a queued correction. `humans_talking` is a
genuine finding: given five lines nobody addressed to it, the arm narrated
them back to the room ("Thanks, Priya — confirmed: second week of
October…"; "Bob, Daniel said the platform team needs to attend at least day
one") — a loop whose only output is a reply will always produce a reply.
The live roles behaved as designed: Daniel re-asked when no answer came in
time, Priya answered the assistant's paraphrase. One run; read it as a shape,
not a number.

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

## Voice — the next transport

The scenes do not change. Needed, per arm: a room the arm can join as a
participant with its own identity (LiveKit for `unify_meet`; hermes's
Discord voice or Meet bot; OpenClaw's Talk session or Meet extension — never
a harness-supplied audio path, which is the capability under test); persona
voices as separate audio tracks so speaker attribution is a real problem;
utterance start/end per participant from the transport, so in-time and
overlap are timestamps; and the assistant's utterance text from the arm
where it speaks from text, otherwise a declared transcription model.

What not to measure here: barge-in latency in milliseconds, disfluency,
prosody. The purpose-built rigs measure those better and would invite the
comparison.
