# meeting — designed, not built

Several people on a call, one assistant among them. Does it speak when it is
spoken to, stay quiet when two humans are talking to each other, answer
before the moment has passed, and turn what it was asked to do into work
that happens later?

## Why this track exists

The turn-taking benchmarks (τ-Voice, Full-Duplex-Bench, EchoChain) are
dyadic: one human, one agent, and they measure barge-in latency and
disfluency handling far better than this suite could. Multi-party is
unmeasured. So is the seam this suite is built around: a request made in a
call that has to become a durable task and fire correctly next week.

The comparison harnesses are not empty here, and the track must not be
built as if they were. hermes joins Discord voice channels with per-speaker
attribution and has a Google Meet plugin with realtime duplex speech.
OpenClaw has Talk mode on four platforms and Google Meet / Zoom / Teams
extensions. What neither has is an arbiter for *whether to speak now* when
three humans are talking: hermes gates on wake-word or mention, OpenClaw's
`talk.session.steer` classifies the human's speech, not the agent's turn.
unify's fast brain runs a structured `silence | defer | smalltalk |
continuation | hang_up` decision every turn with a group-call block injected
at two or more other participants, plus `ProactiveSpeech` for breaking a
silence and a `MeetFloor` protocol between assistants. That is the mechanism
under test — and it has no live multi-human evaluation in unify's own suite.

## Scenarios

All outcome-scored. Every check is a fixture-witnessed effect or a timing
read off the transport; nothing is judged.

| Scenario | Set-up | Checks |
|---|---|---|
| `addressed_by_name` | Daniel: "…can you tell us the deploy window?" | assistant utterance within the answer window; utterance carries the fixture literal (`thursday`, `14:00`) — **disclosure control** |
| `humans_talking` | Daniel and Priya discuss a venue for 40 s, never addressing the assistant | zero assistant utterances in the window |
| `answered_in_time` | Bob asks a factual question, and the script moves on after 8 s | first assistant utterance starts before the persona's next scripted line |
| `commanded_work` | Priya: "…and can you send me that summary every Monday morning?" | a recurring task exists after the call and fires correctly when driven — scored with the `standing/recurring_report` machinery |
| `interrupted_mid_answer` | assistant is answering; Daniel talks over it and changes the question | the assistant's *next* utterance answers the new question and does not replay the old one (fixture literal for each) |
| `two_assistants` (variant) | a second assistant is on the call | at most one assistant answers a question addressed to "the assistants"; no overlap of assistant audio |

`addressed_by_name` is the disclosure control: an arm that is simply silent
passes `humans_talking` and fails this. Both are required.

## What stays deterministic, and what does not

Same split as the text tracks. The **flow** — who speaks, when, what they
say unprompted — is scripted audio: persona lines are text rendered to
speech once, cached by content hash, and injected at waypoints defined by
the assistant's own progress (utterance ended, silence of N seconds), never
by wall clock. What the assistant **elicits** — a persona answering a
question the assistant asks on the call — goes through the persona pool
and live TTS, and is metered separately.

Ground truth stays in the fixture. The deploy window, the venue, the summary
recipient are literals; disclosure is containment on the assistant's
utterance text, which is exact for arms that synthesise speech from text and
is a transcription for arms that do not (record which).

## Adapter requirements — the reason it is not built

The transport does not exist in the harness yet. Needed, per arm:

- **A room** the arm can join as a participant with a distinct identity:
  LiveKit for `unify-cm` (its `unify_meet` channel), and whatever the arm's
  own meeting surface is otherwise (hermes: Discord voice or its Meet bot;
  OpenClaw: Talk session or the Google Meet extension). The harness must
  never supply the arm's audio path — that is the capability under test.
- **Persona voices**: TTS for scripted and elicited lines, one voice per
  participant, injected as separate audio tracks so speaker attribution is
  a real problem and not a courtesy.
- **Timing capture**: utterance start/end per participant from the transport
  (LiveKit track events, or VAD on the mixed audio for arms that give
  nothing better), so `answered_in_time` and `two_assistants` are two
  timestamps, not a judgement.
- **Utterance text**: from the arm where it speaks from text; otherwise a
  fixed transcription model, declared, with the transcript committed.

`unify-cm` today boots with `enable_comms_manager=False` and imports LiveKit
only to dodge a plugin-registration crash; the fast brain is not driven at
all. That is the adapter work, and it is substantial. Build the transport
once, medium-agnostically, and `attribution/stay_silent` and
`interruption/*` gain a voice variant for free.

## What not to measure here

Barge-in latency in milliseconds, disfluency handling, prosody. The
purpose-built rigs measure those; a number from here would be worse than
theirs and would invite the comparison.
