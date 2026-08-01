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
| [`standing`](colleague/tracks/standing/) | What does firing N cost, and does the automation survive drift? | **complete** — 4 experiments, 4 arms |
| [`interruption`](colleague/tracks/interruption/) | Does a mid-task correction land before the wrong thing happens? | designed |
| [`attribution`](colleague/tracks/attribution/) | Many people, one assistant: right person, nothing leaked, silence when correct | designed |
| [`inheritance`](colleague/tracks/inheritance/) | Does the worker act on the right referent without a round-trip? | designed |
| [`continuity`](colleague/tracks/continuity/) | Is a follow-up a warm turn or a cold restart? | designed |
| [`concurrency`](colleague/tracks/concurrency/) | Several tasks, several people — does each correction land in the right one? | designed |
| [`teaching`](colleague/tracks/teaching/) | Does a walked-through workflow become a reusable artifact? | designed |

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
bash colleague/tracks/standing/recurring_report/run.sh
```

Requires `OPENROUTER_API_KEY`, plus a `UNIFY_KEY` for the unify arm and local
checkouts of whichever comparison harnesses you want to run.

## License

MIT. See [`LICENSE`](LICENSE).
