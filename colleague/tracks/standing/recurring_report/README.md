# Recurring weekly report

**Question:** given one natural-language request — *"every Monday, pull last
week's orders, compute the totals, and deliver a report"* — what does each
architecture converge to unattended, and what does week-N cost look like?

**Unify's expected lifecycle** (all mechanized, none hand-configured):

1. `setup` — the CodeAct actor turns the utterance into a recurring
   `TaskScheduler` task (no entrypoint yet, per the actor's own policy).
2. `run_1` — the task executes description-driven (full CodeAct loop). The
   post-run review ("Storing reusable workflow") may store a
   `FunctionManager` function from the trajectory and attach it as the task's
   `entrypoint`.
3. `run_2+` — `TaskScheduler.execute` sees the entrypoint and executes the
   stored function **without invoking the CodeAct LLM loop**
   (`_CodeActEntrypointHandle`): the expected steady state is **0 LLM calls,
   0 tokens**, with a bounded LLM repair loop only on failure.

The hermes-agent comparison arm (old-regime driver, retired)
applies the identical protocol: the same utterance via headless
`hermes chat -q` in a throwaway `HERMES_HOME`, then manual
`hermes cron run` fires of whatever the agent created, metered by a local
recording proxy in front of OpenRouter (`colleague/arms/proxy.py`). First
result: the hermes agent also converged to a zero-LLM steady state
(`no_agent` cron + standalone script), but encoded the schedule as
hourly-on-Mondays with an in-script wall-clock gate — off-spec, and inert
when fired on demand (see the `*-hermes` results NOTE.md).

The OpenClaw arm (old-regime driver over the shared toolkit in
`colleague/arms/openclaw.py`, retired) applies the
same protocol via a throwaway `OPENCLAW_STATE_DIR`, a managed Gateway
child, and `openclaw cron run` fires. Measured result: the cheapest setup
of the three arms by an order of magnitude (67k tokens) and 4/4 exact
on-demand deliveries — but no zero-token steady state exists to converge
to: every fire boots an agent turn (~16.8k tokens), forever (see the
`*-openclaw` results NOTE.md).

The OpenCode arm (old-regime driver, retired) has no
scheduler to register with, so the harness executes whatever the agent
itself declared — preferring the command named in any crontab spec it
writes. Measured result: **0/4 delivered when fired as declared**, because
the agent encoded "every Monday 09:00" as an hourly job whose script exits
unless the clock reads Monday 09:00 UTC — independently reproducing the
same off-spec shape hermes chose. Its setup is the cheapest of any arm
(85k) and the script itself is exactly correct: an earlier run that fired
the script bare, bypassing the gate, delivered 4/4 byte-exact reports (see
both `*-opencode` NOTE.md files).

The prime-agent arm (old-regime driver, retired, driving the
shared fire-series arm, since retired) keeps one resident JSONL-RPC
session across setup and every fire, because that is where the product's
scheduler delivers its job prompts. Measured result: **4/4 exactly right**,
and no distillation of any kind — no scheduled job registered (the model has
no scheduling tool on the RPC surface), no script left in the workspace; the
resident session is the automation, so every fire is a prompt into it
(2–5 LLM calls, ~38k–90k prompt tokens) and the per-fire cost carries the
session's accreting context. Setup is mid-pack at 134k. The zero-token
steady state the unify/hermes/opencode arms converge to does not exist on
this architecture (see the `*-prime-agent` results).

## Task definition

- Fixture: a seeded deterministic orders API (`fixture.py`), four regions,
  integer cents — every (seed, date) produces identical data forever.
- Delivery: `POST /report` to the fixture; the harness scores each delivered
  report field-by-field against independently recomputed ground truth
  (exact integer equality; ±0.005 on the rounded percent). No LLM judging.
- The exact utterance is `UTTERANCE_TEMPLATE` in `harness.py` and is recorded
  verbatim in every result file.

## Protocol

- Target: **staging Orchestra** in an isolated context tree
  (`colleague/tracks/standing/recurring_report/<run-id>/...`), never a real
  assistant. `UNILLM_CACHE=false` — every number is real inference.
- The harness boots the brain standalone (same wiring as the
  ConversationManager sandbox), issues the utterance once, then drives N
  weekly wakes through `TaskScheduler.execute` with the same delegate
  mechanics the production ConversationManager uses for due tasks.
- Accounting: unillm's process-global LLM event hook records every call
  (model, prompt/completion tokens, provider cost) into a per-phase ledger.
  Calls outside phase windows surface in a `background` bucket rather than
  disappearing.
- All simulated weeks trigger on the harness's real run date, so every run's
  report covers the same "previous Mon–Sun" window (recorded per run). Known
  v1 limitation; it does not affect token accounting, which is the headline
  metric.

## Run it

```bash
python -m colleague.tracks.standing.run recurring_report --arm unify-cm
python -m colleague.tracks.standing.run recurring_report --arm hermes-tui
python -m colleague.tracks.standing.run recurring_report --arm openclaw-gateway
python -m colleague.tracks.standing.run recurring_report --arm opencode
```

Knobs (env): `RWR_RUNS` (default 4), `RWR_SEED`, `RWR_PORT`,
`RWR_ORCHESTRA_URL`, `RWR_UNIFY_KEY`, `RWR_PHASE_TIMEOUT_S`.

Outputs land in `results/<run-id>/`:

- `results.json` — full record: utterance, task snapshots, per-run reports +
  scores, per-phase token/cost table, the stored entrypoint function source
  (when attached).
- `ledger.jsonl` — every LLM call (model, tokens, cost, origin).
- `summary.md` — the human-readable table.

> **Old-regime results.** Every measured figure below was produced under
> the retired installed-and-fired regime: the brief was planted through
> harness internals (`actor.act()`, one-shot CLI turns) and the recurring
> mechanism was fired deterministically by per-arm drivers that no longer
> exist, under the retired arm names (`unify`, `hermes`, `openclaw`,
> `prime-agent`). The figures stand as the committed record — each came
> from a committed summary — but they are **not comparable** with
> person-shaped runs, which deliver the brief through the arm's
> conversation surface and let the system decide how the work recurs
> (see `SCENARIO_CHANGES.md`, 2026-08-21). Person-shaped reruns replace
> this table as they land in `results/`.

## Reading the numbers

The claim is falsifiable on three axes visible in `summary.md`:

- **Convergence**: does `entrypoint_after` flip from `None` to a function id
  without any prompt engineering? If not, that is a real finding — the fix
  belongs in the actor/review prompts, not in the benchmark.
- **Steady state**: `run_2+` should show `LLM calls = 0`. Any nonzero value
  is either a repair loop (visible in the ledger) or a leak in the claimed
  architecture.
- **Correctness**: every delivered report must match ground truth exactly —
  a zero-token run that delivers a wrong report is a failure, not a win.
