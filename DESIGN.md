# Colleague — design

## What is being measured

The harness, not the model. Every arm gets the same pinned model and the same
plain-English request; what varies is the architecture around it.

The organising question is what it is like to *have* an assistant rather than
to *invoke* one. Three properties follow from that, and every track is a
measurable consequence of one of them:

1. **Work outlives the conversation.** Something said once keeps happening,
   and keeps being correct as the world moves.
2. **The conversation continues while the work runs.** A correction, a
   question, or a second request arrives mid-task and has to land somewhere
   sensible.
3. **More than one person is talking.** Several people share one assistant,
   with different standing, different information, and different claims on
   its attention.

Property 1 is the `standing` track, which is complete. Properties 2 and 3 are
the six tracks that follow, and are the reason this repo exists separately
from a blog appendix.

## What already exists elsewhere

Worth reading before adding a track, so the suite does not re-measure
somebody else's axis less well than they did.

**Harness-varying, single-shot.** [Harness-Bench](https://arxiv.org/abs/2605.27922)
is the closest prior art: 106 tasks, 5,194 trajectories, comparing OpenClaw,
ZeroClaw, Hermes, Moltis, NullClaw, NanoBot and Codex with the task fixed. Its
limitations section explicitly excludes long-term recurring execution and
persistent automation. [Claw-SWE-Bench](https://arxiv.org/abs/2606.12344)
makes harness and cost first-class for SWE tasks;
[PolyWorkBench](https://arxiv.org/abs/2607.06008) finds harness choice moves
Pass@1 by 8–21 points on one model; [HAL](https://hal.cs.princeton.edu/) is a
cost-aware third-party leaderboard.

**Same thesis, no shared yardstick.** [PreAct](https://arxiv.org/abs/2606.17929)
(compile the first success, replay with no per-step LLM calls),
[Progressive Crystallization](https://arxiv.org/abs/2607.07052) and
[SKILL.nb](https://arxiv.org/abs/2606.08049) all argue distillation beats
re-derivation. None of them share a benchmark. The `standing` track is one.

**Conversation, single-session.** [τ-Voice](https://arxiv.org/abs/2603.13686),
[Full-Duplex-Bench v3](https://arxiv.org/abs/2604.04847),
[EchoChain](https://arxiv.org/abs/2604.16456) (state-update reasoning under
interruption), [IHBench](https://arxiv.org/abs/2606.19595),
[EVA-Bench](https://arxiv.org/abs/2605.13841) and
[AgentChangeBench](https://arxiv.org/abs/2510.18170). These are strong,
purpose-built rigs. **Do not compete with them on turn-taking, barge-in or
disfluency.** They will win, and should.

**The gap.** Nothing joins the two. Conversation benchmarks end when the
session ends; harness benchmarks never have a conversation. Multi-party
human-to-agent is essentially unmeasured — the nearest names
([TeamBench](https://teambench.github.io/),
[CooperBench](https://arxiv.org/abs/2601.13295)) are agent-to-agent
coordination, a different problem.

## Non-negotiable rules

These are what make a vendor-authored benchmark worth reading. Any new track
must satisfy all of them.

**1. Outcome scoring only.** Score externally observable effects — a message
sent or not sent, a row written, a referent chosen from a known set, a task
created. Never score prose quality, and never score whether an arm possesses
a particular abstraction.

**2. No LLM judges.** Fixtures are seeded and deterministic; the harness
independently recomputes the correct answer. If a track cannot be scored this
way, it is not ready to be built.

**3. Probe capabilities others lack — and say so, rather than scoring it
zero.** An earlier version of this rule required every track to be winnable
by a monolithic agent. That was the right rule for a suite about recurring
automation and the wrong one here, because the tracks worth building are
precisely the ones most harnesses have no answer for. Refusing to measure
those would not make the benchmark fairer; it would make it uninformative.

What replaces it is a reporting discipline, in three parts.

*Score outcomes, never mechanisms.* Every check is about what happened —
which address received mail, which figure appeared in a reply, which digest
changed. No check asks whether an arm has a ContactManager.

*Give each arm its own best mechanism.* The `interruption` track does not
demand a live interjection. It offers the correction and lets each arm cope
however it can: unify interjects, OpenClaw queues a turn, hermes and OpenCode
have nowhere to put it. All three are recorded as what they are.

*"No mechanism" is a declared outcome, not a loss.* `UNSUPPORTED` is kept out
of the accuracy denominator and reported in its own column. An arm with no
running loop is not failing to steer; it is not steering. Presenting that as
a zero would be the press-release version, and the difference between the two
is entirely in the reporting.

Where a track genuinely can be won by careful reading alone — `attribution`
and `custody` both can — the per-track README says so explicitly, so the
result is read as "structure versus care" rather than as a capability gap.

**3a. Every track carries a disclosure control.** A scorer that only rewards
refusal will report a silent arm as perfect. `custody/asked_operational`
requires a disclosure; `attribution/two_askers` requires two correct answers,
not two refusals; `teaching/untaught_control` establishes what the API alone
yields so a later score can be read as retention. These are declared as
calibration points in `colleague/selftest.py`, with reasons.

**3b. The suite self-tests.** `python -m colleague.selftest` runs every track
against a scripted mock arm under two plans: `ideal`, what a competent
assistant would do, and `naive`, the plausible wrong thing. Ideal must be
credited and naive must score *differently* — not necessarily worse, since on
`continuity` the naive behaviour reaches the right answer expensively, which
is exactly `DEGRADED`. A scenario whose ideal plan cannot pass is unwinnable;
a scorer that returns the same verdict for both is measuring nothing. Both
were caught by this check during the build.

**4. Identical utterance, no hand-tuning.** Each system self-organizes from
the same plain English. We measure the floor the design converges to
unattended, not the ceiling an expert config reaches. A hand-tuned ceiling
protocol is a legitimate separate experiment; it is not this one.

**5. Publish losses at the same volume as wins.** unify's first drift run
failed at 4/10 and exposed four production defects. That is in the committed
results and stays there.

**6. Pinned identical model across arms.** Currently `openai/gpt-5.6-sol` via
OpenRouter. An arm that cannot run the pinned model is a methodological
problem to be stated, not worked around silently.

**7. Trigger-based synchronisation, never sleeps.** Ordering between the
scripted interlocutor and task progress must be deterministic, so cached
(millisecond) and live (multi-second) runs order identically.

## Tracks

### `standing` — work that outlives the conversation

**Complete.** Four experiments, four arms. See
[`colleague/tracks/standing/`](colleague/tracks/standing/).

| Experiment | Question |
|---|---|
| `recurring_report` | Setup cost, per-firing cost over N weeks, schedule fidelity, correctness on demand |
| `drift_recovery` | An API field is renamed mid-series: cost and reliability of recovery, with and without a human |
| `semantic_triage` | Recurring work with a judgment substep: steady-state cost at equal accuracy |
| `policy_propagation` | One rule across three automations, one change request: propagation completeness and cost |

The finding that shapes the rest of the suite: the arms sort into two pairs.
Script steady states (hermes, OpenCode) are free per firing and cannot
self-heal. Model-in-loop steady states (unify's repair path, OpenClaw's agent
turn) recover unattended and pay for it. unify is the only arm that is in
both categories — free when nothing is wrong, model-backed when something is.

### `interruption` — does a correction land in time

A task is running. A correction arrives as an ordinary text message. Does it
reach the work before the wrong action is taken?

*Scoring:* the wrong action is externally observable and irreversible within
the fixture (an email to the wrong address, a write to the wrong account).
Binary per scenario. Secondary metrics: latency from correction to effect,
and whether the arm redirects or restarts (restart cost is measured in tokens,
not judged).

*Fairness:* every arm can queue, restart, or ignore. All three are legitimate
strategies and all three are scoreable on the same outcome.

### `attribution` — many people, one assistant

Several people in one shared channel. Different standing, different
information, different claims on attention.

*Scoring:*
- Did the answer reach the person who asked?
- Was information scoped to one person disclosed to another? (leak: binary)
- Was the request attributed to the right person's resources — whose
  calendar, whose account?
- Did it stay silent where silence was correct? (over-speaking rate, scored
  as "a message was sent", never as message quality)

*Fairness risk — the highest in the suite.* Scenarios must be solvable by an
agent that simply reads the channel carefully. Do not require a contact
registry to pass. The interesting result is whether careful reading is
*enough*, not whether the competitor lacks a `ContactManager`.

### `inheritance` — the right referent, without a round-trip

The conversation has touched two documents and two people with the same first
name. A request is dispatched that is unambiguous from inside the
conversation and ambiguous from outside it.

*Scoring:* which referent was acted on, from a known set. Plus clarification
round-trips consumed, and wrong-confident-action rate (acting on the wrong
referent without asking is the worst outcome and is scored separately from
asking).

*Fairness:* this is the cleanest track. Every arm has some way to carry or
not carry context into delegated work; the experiment measures the
consequence, not the mechanism.

### `continuity` — warm turn or cold restart

A completed task gets a follow-up: "now do the same for March." Measure
re-derivation cost and correctness. Extended forms: across a process
restart, and across mediums (asked in chat, followed up by email).

*Scoring:* correctness of the follow-up result, plus tokens and wall-clock to
produce it, against the same task run cold as a baseline.

### `concurrency` — several tasks, several people

Multiple automations in flight, corrections arriving from more than one
person, notifications emitted by the running work.

*Scoring:* did each correction land in the intended task (routing accuracy,
from a known mapping); were notifications that mattered surfaced and the rest
suppressed (against a labelled fixture); did anything deadlock or get dropped.

### `teaching` — does a walkthrough become an artifact

A workflow is walked through in text, carrying two rules that are absent from
the API: a threshold that is not the obvious one, and a vendor chased through
their account manager. A later week is requested with nothing restated.

*Scoring:* the exact set of reminder recipients, recomputed. An untaught
control establishes what the API alone yields, so the taught week's score can
be read as retention rather than inference.

### `custody` — where knowledge is kept decides who can reach it

Three facts arrive in one briefing: an operational detail, someone's medical
condition, and a credential. Later, a contractor asks about each.

*Scoring:* disclosure by containment of a distinctive literal, per question.
One of the three *must* be disclosed, so an arm cannot pass by refusing
everything.

*Fair reading:* every arm can pass this by judgement alone. The architectural
claim is that a scoped store decides once at write time while a flat store
re-decides on every question — and this v0 does not yet separate those,
because it asks immediately rather than after a long intervening
conversation. Stated in the track README rather than implied by the score.

## Infrastructure this needs

**The scripted interlocutor** is the main new component and gates tracks
`interruption`, `attribution` and `concurrency`. It injects messages from
named participants at points defined *relative to task progress*, not
wall-clock — the same discipline as unify's `tests/async_helpers.py`. Build
it before writing scenarios for those tracks, because it determines what is
expressible.

Requirements:
- Named participants with distinct identities on whatever channel an arm
  exposes
- Injection points keyed to observable task state, not elapsed time
- Deterministic replay: the same run twice produces the same interleaving
- Per-arm adapters, since arms differ in how a second person can even reach
  them (this is itself a finding worth recording — an arm with no concept of
  a second sender should be reported as such, not scored as a failure)

**A unified entrypoint.** Currently each experiment ships its own
`run_<arm>.sh`. Once the interlocutor lands, these should collapse into one
runner taking track, experiment and arm.

## Repository layout

```
colleague/
  arms/            per-harness toolkits (hermes, openclaw, opencode, proxy)
  harness/         shared infrastructure (ledger; interlocutor to come)
  tracks/
    standing/      four complete experiments, each with results/
    <six others>/  designed, not built
```

Arm toolkits are peers of the experiments, not children of one of them. The
`standing` experiments were originally written with the shared OpenClaw and
OpenCode toolkits living inside `recurring_report`; that is fixed.

## Status

All seven tracks are built and self-testing. None has been run against a live
arm yet — every published number in this repo is still `standing` only.

| Track | Scenarios | Notes |
|---|---|---|
| `standing` | 4 experiments | Complete, four arms, published |
| `inheritance` | 3 | |
| `interruption` | 3 | Expect `UNSUPPORTED` for hermes and OpenCode |
| `continuity` | 1 + 1 control | |
| `attribution` | 4 | |
| `custody` | 2 + 2 controls | |
| `concurrency` | 1 | Thinnest track; models a batch, not true concurrent dispatch |
| `teaching` | 2 + 1 control | Text walkthrough; the image variant is not built |

## Next

1. Run all seven against all four arms and publish the results
2. `concurrency` needs a runner that holds several handles at once, so
   corrections arrive against genuinely independent in-flight tasks
3. `custody` needs the long-intervening-conversation variant, which is the
   version that would actually separate scoped storage from careful judgement
4. `teaching` needs the screenshot-carrying variant
5. Drive the unify arm through ConversationManager rather than `CodeActActor.act`
   — the conversation layer is the faithful surface for these tracks, and
   `act` is a v0 convenience inherited from `standing`

## Open questions

- **Held-out scenarios.** [Rethinking the Evaluation of Harness
  Evolution](https://arxiv.org/abs/2607.12227) shows harness gains largely
  evaporate on held-out tasks. If this suite is ever used to tune unify, a
  held-out split stops being optional.
- **Third-party reproduction.** The drivers are here to make it possible;
  nobody has done it yet. Until someone has, the results are self-reported.
- **Arms with no scheduler and no multi-user surface** may be unable to
  express several tracks. The honest treatment is to report the architectural
  limit explicitly rather than record a zero, as the `standing` track already
  does for OpenCode's policy propagation.
- **Voice** is a later transport, not a track. Every track above is written
  medium-agnostically so voice slots in without redesign — but the
  purpose-built voice rigs listed above are better at what they measure, and
  the only defensible voice contribution here would be voice *commanding
  durable work*, which is a variant of `standing` rather than a new axis.
