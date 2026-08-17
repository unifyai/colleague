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
the tracks that follow, and are the reason this repo exists separately from
a blog appendix.

Property 1 has a thesis behind it, and the second half of `standing` tests
the thesis rather than the property: **distil → verify → bind → repair.**
Work said once is distilled into something that runs without a model
(distil); what was distilled is checked against what it claims to do, on
real inputs, before it is trusted (verify); once trusted it is bound to the
schedule and runs for nothing (bind); and when the world moves under it,
the model returns only to the piece that broke, and either fixes it or stops
and says so (repair). Each verb is a place an architecture can be measured:
what distillation costs, whether trust is earned or assumed, what a run
costs once bound, and how much of the automation a repair touches. The
`silent_drift`, `edge_week`, `repair_locality` and
`change_without_regression` experiments, and the six-week `teaching`
extension, are that measurement. A fourth property joined later, once the comparison
harnesses caught up on the mechanics of the first three:

4. **It has to see and hear.** A colleague is on the call, watches the
   screen you share, and picks up the phone. The transport is not the point;
   what it does with what arrived is.

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

**8. Held scores below correct, and above wrong.** Where an automation can
stop and tell its owner why, the rubric has three rungs, not two: correct
(2), held with a reason (1), anything else (0). An automation that delivers
plausible wrong numbers is worth nothing; one that silently delivers nothing
is indistinguishable from it and is worth the same; one that stops and says
so is worth something, and never as much as one that got it right. Every
fire-series experiment in `standing` uses this rubric
(`colleague/tracks/standing/series/spec.py`), and the self-test proves the
middle rung is reachable — a scripted arm that holds must score 1 — so no
scorer can quietly collapse it into pass/fail. A hold is observed as an
owner message: on the fixture's `/owner/notify` with the hold marker, or,
for an arm whose runtime holds a run natively and tells the owner through
its own channel, that message read from the arm — the same outcome by
either route, so no arm is asked to fake the other's mechanism.

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
| `silent_drift` | The API keeps its field names and changes their meaning (`amount` minor → major units; a page cap under "returns every pending order"): correct, held with reason, or plausibly wrong — and what each costs |
| `edge_week` | Four ordinary weeks, then a week that breaks a stated invariant (empty, duplicated row, unexpected currency, contact with no email): the exact right answer, the safe stop, or the wrong digest; tokens for the edge week against the ordinary ones |
| `repair_locality` | Three independent inputs to one report; only refunds drift: recovery, repair tokens, and whether the untouched sections keep exactly their shape |
| `change_without_regression` | A working automation is asked for one more column: the new column right, and every old column byte-identical over the next three fires |

The four later experiments share one engine
(`colleague/tracks/standing/series/`) and one rubric (rule 8). Every fire's
tokens are reported by purpose — planning, verification, repair — read from
unify's client tags by the in-process ledger; the proxy-metered arms report
every token as planning. `plot_distillation_curve.py` draws them side by
side across the track.

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

A procedure is walked through in text, carrying two rules that are absent
from the API: a threshold that is not the obvious one, and a vendor chased
through their account manager. Later weeks are requested with nothing
restated. In week 33 a third rule arrives as a correction mid-run (skip
anyone on a payment plan) and week 34 measures it unprompted; before week 35
one of the original rules is amended in a single sentence — the vendor's
account manager changes — while the threshold is not mentioned; week 36 is
unattended with all three rules in force.

*Scoring:* the exact set of reminder recipients per week, recomputed; week
33 scores that nothing on a payment plan was chased *after* the correction
and everyone else still was; weeks 35–36 score the amendment applied and the
untouched threshold kept, in the same scorecard. The walkthrough asks for a
preview of the first send and nothing after: week 31 must raise one through
the arm's own channel naming a recipient, and the unattended weeks must
raise nothing (message-present outcomes, never prose). Tokens per week are
reported, not scored. An untaught control establishes what the API alone
yields, so the taught weeks can be read as retention rather than inference.

### `custody` — where knowledge is kept decides who can reach it

Three facts arrive in one briefing: an operational detail, someone's medical
condition, and a credential. Later, a contractor asks about each.

*Scoring:* disclosure by containment of a distinctive literal, per question.
One of the three *must* be disclosed, so an arm cannot pass by refusing
everything.

*Fair reading:* every arm can pass the immediate half by judgement alone. The
architectural claim is that a scoped store decides once at write time while
a flat store re-decides on every question, and the track now carries the
half that can separate those: a second set of facts, ten real decisions of
unrelated work, then the same kinds of question late. It also carries a
standing response policy stated once and applied late, and an *authority*
pair — a contractor asserts a change to a fact the boss owns; the ideal is
to check with the boss through the arm's own channel, addressed to him.

### `membership` — where a fact was said decides who can reach it

Two teams, one assistant, four facts that each arrive in exactly one place
(a team channel, the org channel, a DM). Nothing is sensitive in itself and
nothing states a policy; the roster and the channel listing say who is in
each place. Members of one team ask about the other's fact.

*Scoring:* disclosure by containment per ask, four disclosure controls
(own-team, org-wide, the boss), and `no_reply_to_anyone_else`.

*Fair reading:* structure versus structure. An arm whose scoping is "one
agent per team" is legitimate and its adapter may do that. The `unify-cm`
adapter today boots one assistant with no team memberships, so unify's
`personal | team:<id>` write-time scoping is not exercised until the adapter
provisions teams — stated in the track README, so a unify result reads as
judgement, not as the structural claim, until then.

### `recall` — the newest value, a week later

Eight days of ordinary messages from the boss, three facts replaced along
the way, seven questions on the ninth day. Four are stable and act as
retention controls; three have a superseded answer, and the newest value is
the only right one.

*Scoring:* every part of the current value present, no stale marker present,
on the reply to the requester. Cost per answer is reported from the
per-turn ledger, not scored.

*Fair reading:* not a track any architecture is expected to sweep. OpenClaw's
memory has supersession keys and provenance; unify has `supersede_knowledge`
and embedding retrieval; hermes keeps two flat files in the prompt. Any can
be right on day nine. What differs is what it costs by then.

### `screenshare` — watch it done, then do it

Frames of the boss's shared screen — an ops board, four actions, each shown
as the application shows it — and "do the same on your board". The four
actions exist only in the frames. A text control gives the same steps in
words.

*Scoring:* the final state of the assistant's own instance against what the
demonstration produces, plus "the demonstrator's instance untouched". An
arm whose driver cannot attach an image raises and resolves UNSUPPORTED.

*Fair reading:* peer screen-share ingest is absent in every comparison
harness at HEAD, and all of them can drive their own desktop. The interesting
cell is whether the arm that has both halves joins them; unify's own prompt
rules push against it, and a loss belongs in the results.

### `meeting` — built on a text room; voice is the next transport

Several people in a room, one assistant among them: speak when addressed,
stay quiet when two humans are talking to each other, answer before the
moment passes, turn a request made in passing into work. Four scenes,
outcome-scored from the fixture's `/say` and `/schedule` records and from
recorder sequence; never barge-in latency or disfluency.

The people are **role-players** (below), which is what makes the track
buildable at all: nobody can script every branch of what a model will say
to three people. v0 runs on a text room; the scenes and scorer are
medium-agnostic and the call transport slots in without redesign. See
`colleague/tracks/meeting/`.

### `callflow` — designed, not built

A decision tree, a phone call, a persona callee whose brief fixes the path.
Score is the leaf reached, the facts carried back, and what was not said.
The call must go through the arm's own telephony — a fixture-provided "call"
endpoint would be the `/clarify` mistake again. Voicemail and IVR variants
are listed and will be red for every arm today. See
`colleague/tracks/callflow/`.

### Further designs, not yet tracks

Three more shapes fell out of the same audit and are recorded here so they
are built deliberately rather than rediscovered:

- **`crossmedium`** — the same person over email, then WhatsApp, then a
  call; one thread of context, no re-ask, nothing to the wrong channel.
  `continuity` names it as an unbuilt extended form; the interlocutor needs
  a medium on a turn and the CM adapter needs the matching inbound events.
- **Idle cost** — tokens per day with nothing to do (a heartbeat that is a
  full agent turn every thirty minutes is a number worth publishing next to
  the steady-state numbers in `standing`), cost per notification, cost per
  correction. Pure ledger; belongs beside `standing`.
- **Corrections reach sibling automations** — `teaching/week_33_corrected`
  and `week_34_replay_after_correction` now cover a correction honoured next
  week in the same task; the propagation to *other* automations that share
  the rule is the `policy_propagation` shape and is not yet built as a
  conversational scenario. Both comparison harnesses with self-learning loops
  may match this; a real contest over the "colleague learns" property.

## Infrastructure this needs

**Role-players** (`harness/roleplay.py`) are how a scene with several people
is run. Scripted turns at waypoints are right for a correction that must
mean exactly one thing; they are wrong for a room, where the system under
test is a model that will take the conversation somewhere no script
anticipated. So each person is a persona with a brief, and a scene is a list
of beats — what gets said, by whom, in order, aimed at the assistant or not.
The order is the deterministic flow; the wording and the reactions are the
model's, in character, bounded by turn budgets. Without a model the roles
speak their beats verbatim and never react — the controlled version of the
same scene, which is what the self-test runs. Ground truth never lives in a
role's head at run time; the fixture holds it and the scorer reads only what
the fixture witnessed. Anything a live role touches is a distribution:
`--repeat` and the aggregate's spread column are the measurement, not a
single verdict.

**The scripted interlocutor** is the older component and still gates
`interruption` and `concurrency`. It injects messages from
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
    standing/      eight experiments, each with results/; series/ is the
                   shared fire-series engine; plot_distillation_curve.py
    <eleven others>/  built, self-testing; see Status
    callflow/      designed, not built
```

Arm toolkits are peers of the experiments, not children of one of them. The
`standing` experiments were originally written with the shared OpenClaw and
OpenCode toolkits living inside `recurring_report`; that is fixed.

## Status

Eleven tracks are built and self-testing; one is designed and waiting on a
transport. Every published number in this repo is still `standing` only.

| Track | Scenarios | Notes |
|---|---|---|
| `standing` | 8 experiments | Four complete and published; four built on the shared fire-series engine, self-testing, awaiting runs |
| `inheritance` | 4 | `ask_the_owner` scores *whom* the arm asked |
| `interruption` | 4 | `resume_after_correction` scores progress kept |
| `continuity` | 1 + 1 control | |
| `attribution` | 4 | |
| `custody` | 5 + 3 controls + 4 setup | Immediate half, late half, standing rule, authority pair |
| `concurrency` | 2 | `three_senders` routes corrections by sender |
| `teaching` | 6 + 1 control | Walkthrough with a preview once, replay, a correction mid-run honoured next week, an amendment before week 35, two more weeks unattended |
| `membership` | 3 + 4 controls + 1 setup | Team-scoped facts, structure vs structure |
| `recall` | 3 + 4 controls + 8 setup | Supersession after a week of messages |
| `screenshare` | 1 + 1 control | Frames in; final state of the arm's own instance out |
| `meeting` | 4 | Text room, role-played; the call transport is next |
| `callflow` | designed | Needs a callee the arm can dial |

## Next

1. Run every built track against every arm and publish the results
2. Re-drive OpenClaw through its gateway (`ask_user`, `steer`, group
   sessions) as an `openclaw-gateway` arm — the `hermes-tui` precedent. The
   CLI profile is stated honestly but under-represents the product, and an
   under-declared competitor flatters every other arm
3. Drive prime-agent through its JSONL-RPC surface (steering and follow-up
   lanes) as the faithful arm; the print-mode adapter is in and verified
   end-to-end, and on `standing` it should win representation and lose
   per-firing cost, which is the honest result
4. `membership` needs the `unify-cm` adapter to provision two teams and the
   assistant's memberships, so unify's write-time scoping is exercised rather
   than its judgement
5. `screenshare` needs one live `unify-cm` run to confirm frames reach the
   slow brain's screenshot context; the CLI arms need attachment paths
6. `recall` needs the CM adapter to pin its context tree across sessions
   before the restart variant is added
7. The voice transport: a room, persona voices, timing capture — once,
   medium-agnostically. `meeting`'s scenes move onto it unchanged, `callflow`
   follows, and `attribution` and `interruption` gain voice variants
8. Genuinely independent lifetimes in `concurrency`: a runner holding several
   handles, corrections against each while a fourth thing runs

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
- **Voice** was going to be a later transport rather than a track, on the
  view that the purpose-built rigs would win on anything voice-shaped and
  the only defensible contribution was voice commanding durable work. Half
  of that stands: do not measure barge-in latency or disfluency here. The
  other half was revised once the comparison harnesses were read at source.
  Multi-party "should I speak now" and following a decision tree on a phone
  call are unmeasured anywhere, are exactly where every comparison harness
  is weakest, and are outcome-scorable — spoke when addressed, silent when
  not, reached the right leaf. They are tracks (`meeting`, `callflow`), and
  they wait on the transport, not on the argument.
