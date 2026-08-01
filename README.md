# Colleague

A benchmark for **agent harnesses**, not agent models.

Every arm receives the identical plain-English request, runs unattended, and
is scored against exact recomputed ground truth. The model is pinned and
identical across arms, so what varies is the architecture: what each system
converges to on its own, what that costs, and whether the result still works
next week.

The question the suite is built around is not *can an agent do this once*.
It is *what is it like to have one around* — several people talking to it,
work outliving the conversation, and the world moving underneath.

## Why this exists

Most agent benchmarks hold the harness fixed and vary the model. The few that
vary the harness — [Harness-Bench](https://arxiv.org/abs/2605.27922),
[Claw-SWE-Bench](https://arxiv.org/abs/2606.12344) — measure single-shot task
completion; Harness-Bench's limitations section explicitly excludes long-term
recurring execution and persistent automation. On the other side, the voice
and conversation benchmarks ([τ-Voice](https://arxiv.org/abs/2603.13686),
[Full-Duplex-Bench](https://arxiv.org/abs/2604.04847),
[EchoChain](https://arxiv.org/abs/2604.16456)) measure a single session in
isolation.

Nothing measures the seam: conversation that commands durable work, work that
outlives the conversation, and several people sharing one assistant.

## Arms

| Arm | What it is | Scheduler |
|---|---|---|
| `unify` | [unifyai/unify](https://github.com/unifyai/unify) — typed tasks + stored functions | first-class |
| `hermes` | hermes-agent — skills, `no_agent` cron | first-class |
| `openclaw` | OpenClaw — gateway + cron whose payload is an agent turn | first-class |
| `opencode` | OpenCode — no scheduler; improvises scripts and host crontab | none |

Non-unify arms are metered by a local recording proxy in front of OpenRouter
(`colleague/arms/proxy.py`); the unify arm is metered in-process through a
chained unillm hook. Both produce the same per-phase ledger.

## Tracks

| Track | Question | Status |
|---|---|---|
| [`standing`](colleague/tracks/standing/) | What does firing N cost, and does the automation survive drift? | **run** — 4 experiments, 4 arms |
| [`inheritance`](colleague/tracks/inheritance/) | Does the worker act on the right referent without a round-trip? | built |
| [`interruption`](colleague/tracks/interruption/) | Does a mid-task correction land before the wrong thing happens? | built |
| [`continuity`](colleague/tracks/continuity/) | Is a follow-up a warm turn or a cold restart? | built |
| [`attribution`](colleague/tracks/attribution/) | Many people, one assistant: right person, nothing leaked, silence when correct | built |
| [`custody`](colleague/tracks/custody/) | Where a fact is filed decides who can get it back out | built |
| [`concurrency`](colleague/tracks/concurrency/) | Several tasks, several people — does each correction land in the right one? | built |
| [`teaching`](colleague/tracks/teaching/) | Does a walked-through workflow become a reusable artifact? | built |

"Built" means the fixture, scenarios and scorers exist and self-test. Only
`standing` has been run against live arms — every number below is from it.

Full scope, scoring rules and the fairness constraints are in
[`DESIGN.md`](DESIGN.md).

## Results so far

The `standing` track is complete across all four arms. Headlines, with full
per-run detail and raw ledgers in each experiment's `results/`:

- **Recurring report** — unify reaches a zero-LLM-token steady state (typed
  task bound to a stored function). hermes and OpenCode also reach zero-token
  steady states via standalone scripts, but both independently encoded
  "every Monday 09:00" as an hourly job gated on a wall-clock check, and
  deliver 0/4 when fired as declared. OpenClaw never distills: every firing
  boots an agent turn, forever.
- **Drift recovery** — the API renames a field mid-series. unify repairs
  itself in one attempt and never dips (10/10). OpenClaw adapts unattended
  (9/10) but its payload never heals, so post-drift firings cost ~2× forever.
  hermes and OpenCode flatline at 4/10 without a human.
- **Semantic triage** — all four arms hit 100% on 96 inquiries. Per-firing
  cost spans two orders of magnitude: unify ~645 tokens (one focused
  `query_llm` call inside distilled code) against ~8.8k–30k for the others.
- **Policy propagation** — one rule, three automations. unify and hermes both
  propagate 15/15; OpenClaw is cheapest to change but drops to 10/15; OpenCode
  cannot reach the scenario at all, building only two separable automations
  from three requests across three attempts.

The suite reports losses as prominently as wins — unify's first drift run
failed outright at 4/10 and exposed four production defects, which is in the
committed results.

## Methodology

- **Real inference.** `UNILLM_CACHE=false`. Every call metered: model, tokens,
  provider cost. Raw ledgers ship with results.
- **Identical utterance, no hand-tuning.** Each system self-organizes from the
  same plain English. We measure what the design converges to, not what an
  expert config can do.
- **Exact ground truth, no LLM judges.** Fixtures are seeded and
  deterministic; the harness independently recomputes the correct answer.
- **Outcome scoring only.** Every track scores externally observable effects —
  a message sent or not sent, a row written, a referent chosen — never
  whether an arm has a particular abstraction.
- **Reproducible.** Local fixture servers, no third-party accounts, no live
  web state.

## A stated conflict of interest

This benchmark is authored by Unify, and `unify` is one of the arms. That is
worth knowing when reading it. The protocol is built to survive it — pinned
identical models, exact recomputed scoring with no LLM judges, committed raw
ledgers for every run, and published failures — but design decisions were
still made by an interested party. Independent re-runs are welcome and the
drivers are here to make that possible.

## Running

Each experiment is standalone, with its own README, fixture, harness and
launchers. Experiments run against staging Orchestra in an isolated context
tree (`colleague/<experiment>/<run-id>/...`), never a real assistant.

```bash
bash colleague/tracks/standing/recurring_report/run.sh   # standing track
python -m colleague.run inheritance --arm unify          # everything else
python -m colleague.run --list                           # tracks and scenarios
```

Requires `OPENROUTER_API_KEY`, plus a `UNIFY_KEY` for the unify arm and local
checkouts of whichever comparison harnesses you want to run.

### Running a sweep in the cloud

A full sweep is dozens of shards making real, uncached LLM calls, and there
is no reason to sit through it serially on a laptop.

```bash
scripts/cloud_run.sh                                    # all tracks, unify arm
scripts/cloud_run.sh --arms all --confirm               # all tracks, all arms
scripts/cloud_run.sh --arms all --repeat 5 --confirm    # distributions, not points
scripts/cloud_run.sh --tracks custody --arms all --dry-run
```

It fires the `Benchmark` workflow and returns a run URL. A shard is one
scenario against one arm — except for tracks that hold a single session
across their scenarios (`continuity`, `custody`, `teaching`), which stay
whole because splitting them would destroy exactly what they measure.
`colleague/plan.py` owns that distinction, so the workflow never has to know
about it.

| Sweep | Shards |
|---|---|
| all tracks, unify | 14 |
| all tracks, all arms | 56 |
| all tracks, all arms, repeat 5 | 280 |

Anything over 40 shards needs `--confirm`, enforced again inside the
workflow. Repeats that disagree are shown as a spread rather than a majority
verdict — when the same scenario passes three times and fails twice, that is
a result about reliability and averaging it away would hide it.

Results land as a merged `summary.md` and `merged.json`:

```bash
gh run download <run-id> --repo unifyai/colleague --name benchmark-summary
```

Credentials come from local env files rather than being pasted in:

```bash
scripts/sync_secrets.sh --dry-run   # report what would be set
scripts/sync_secrets.sh             # set it
```

It reads `~/unify/.env` and `./.env`, pushes `OPENROUTER_API_KEY` and
`UNIFY_KEY` as encrypted secrets and the rest as repo variables. Values are
never printed — each is reported by name, source file and a short SHA-256
fingerprint, which is enough to confirm the right value moved and useless for
recovering it. Values reach `gh` over stdin rather than argv, so they never
appear in the process table. A local `ORCHESTRA_URL` pointing at localhost is
ignored in favour of staging, since CI cannot reach a laptop.

It deliberately will not mirror your `gh auth token`. A developer CLI token
usually carries `repo`, `admin:org` and `delete_repo`, and any secret on a
public repo is readable by a workflow that anyone with write access can add.
If a private harness repo needs one, mint a fine-grained token scoped to
read-only contents on those repos and set `HARNESS_TOKEN` by hand.

An arm whose harness cannot be checked out is recorded as unavailable rather
than failing, so one missing checkout does not take the sweep down.

### Checking the benchmark itself

```bash
python -m colleague.selftest
```

Runs every track against a scripted arm under two plans — `ideal`, what a
competent assistant would do, and `naive`, the plausible wrong thing — and
asserts that ideal is credited and naive scores differently. It makes no LLM
calls. A scenario whose ideal plan cannot pass is unwinnable; a scorer that
returns the same verdict for both is measuring nothing. Both classes of bug
were caught this way during the build.

## License

MIT. See [`LICENSE`](LICENSE).
