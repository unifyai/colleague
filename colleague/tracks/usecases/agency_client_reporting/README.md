# agency-client-reporting

Measures the live page
[unify.ai/use-cases/agency-client-reporting](https://unify.ai/use-cases/agency-client-reporting):
a performance agency's monthly client report, pulled from Google Ads, Meta Ads
and Google Analytics, with the campaigns that went wrong at the top and the
draft going to the account manager rather than the client.

The page carried three figures. None of them had been measured. This track
replaces them with figures from an instrumented run and commits the ledger.

## Result

From [`results/2026-08-04T17-36-52Z-unify`](results/2026-08-04T17-36-52Z-unify/)
(read its `NOTE.md` first — the cost column in `summary.md` is void and the
real figures are reconstructed from billing):

| | measured | the page had claimed |
|---|---|---|
| problems caught | 9 of 9, no false positives — **superseded, see below** | 9 |
| one cycle, 14 clients | **10.3 min** | ~40 min |
| per client report, first month | **$0.2555** | $0.14 |
| per client report, settled | **$0.0224** | — |
| reports | 13 drafted, 1 refused | — |

The page had understated cost by about 2× for a first month and overstated
cycle time by about 4×. Detection was confirmed four times over: ad hoc during
setup, description-driven, through the stored entrypoint, and offline for free.

Setup costs $24 once. The 11× drop between the two per-report figures is the
task settling onto a stored entrypoint, so the page carries both rather than
the flattering one.

### The detection figure is stale

`9 of 9` was measured against a fixture that planted nine anomalies. The
fixture now plants **eleven**: it was missing the realistic dead campaign —
converted normally last month, nothing this month — which is the case where
cost per conversion is a number on one side of the comparison and undefined on
the other. Report code that guards the prior month against `None` and not the
reported one dies on it, and during the misaligned run on 2026-08-04 exactly
that killed three clients' reports, each recorded as `blocked` with a reason
blaming platform data rather than the arithmetic.

So the denominator moved and nothing has been measured against the new one.
Cost, wall-clock, the refusal and the convergence result are untouched by this
— they do not depend on how many campaigns are planted.

The stored entrypoint from the run above **passes** the new fixture: replayed
offline against all eleven plants with the narrative call stubbed, it flags
11/11 with no false positives and no extra blocks, because it routes the
undefined-cost-per-conversion case through its own branch instead of
subtracting. That is a free check of a stored function, not a measurement: it
proves the artifact survives, not that a fresh cycle scores 11 of 11.

**The claim is off the live page** — the `results` array, and the three pieces
of surrounding copy that carried the same count (the scene's speech bubble, the
run-history subtitle, the last timeline row). Under rule 1 of the track's
contract an unmeasured figure comes off rather than being edited up to eleven,
and that applies to the replay's `11 of 11` too: the replay stubs the narrative
calls, so it would sit under a disclosure promising every model call was
metered, and it measures whether a stored artifact survives a harder fixture
rather than what a cycle scores. Cost and cycle time stay on the page — they
come from the metered run and do not move with the plant count.

**A re-run cannot produce the figure yet, so it is not worth paying for today.**
Setup dies before creating a task: the actor web-searches model pricing for its
own narrative step, and that search's summarisation call returns whitespace
instead of JSON, which aborts the task. It cost about $19 on this track on
2026-08-05 before being diagnosed, and the same brief reaches the same path on
the trading-review track. The detection row returns when that is fixed and a
live cycle produces it.

What *is* ready is the window logic: the harness now follows the task's own
reading of its schedule rather than hoping the two regimes agree (see
Protocol), so whether a cycle measures anything is no longer luck.

## What the system is asked

The page's `brief` field, read out of `src/data/useCases.tsx` at run time and
passed through untouched — sha256 recorded in every result file, so an edit to
the page's ask invalidates the figures rather than silently inheriting them.

Alongside it: the fixture's endpoints (standing in for three OAuth
connections the brief says to connect) and the shape of the hand-over POST.
Nothing else. In particular the system is not told which month to report, that
there are 14 clients, how to read "held steady" or "more than a third", or
what to do about the account whose Meta connection is dead.

## The fixture

`fixture.py` — stdlib-only, seeded, 14 fictional clients, 108 campaigns across
the two platforms, deterministic forever for a given seed.

Baselines are generated inside safe zones: spend and conversions wobble ±6%
month over month on a base of ≥60 conversions, which keeps every ratio far
away from all three of the page's thresholds, and every baseline campaign
converts, so a rule-C burner can only be a plant. Eleven anomalies are planted
across eight clients in the reported month pair, in four shapes:

| Plant shape | Count | Rules it trips (the page's words) |
|---|---|---|
| conversions collapse while spend holds or rises | 3 | held steady or rose while conversions fell by more than a third |
| cost per conversion swings | 3 (two worse, one better) | cost per conversion moved more than 40% |
| a burner that converts nothing in either month | 3 | spent over $200 and converted nothing |
| **converted last month, nothing this month, spend up** | **2** | **both of the above two at once** |

The fourth shape plants no new rule — it is the combination the first three
never produced, and the only one where cost per conversion is defined in the
prior month and undefined in the reported one. It exists because report code
that guards one side of that comparison against `None` and not the other
crashes on it, and a fixture that never generates it scores such code as
correct.

Ground truth is recomputed from the *served* data, never the generator's
intent, and `--selftest` sweeps the tolerance choices a reasonable reader
might make (`steady_floor` 0.90–1.00, `fall_ratio` 0.63–0.70, `cpa_move`
0.36–0.44) asserting the flagged set never moves. It also asserts no month
pair outside the anchor pair trips anything, and asserts the fourth shape
directly — healthy conversions in the prior month, zero in the reported one,
spend clear of the $200 threshold, tripping exactly those two rules under
every tolerance in the sweep — rather than leaving it to the campaign-set
comparison.

Passing that sweep at one seed is not the same as passing it at any seed.
`ACR_SEED` is a documented knob, so a user can reach a seed the fixture was
never tuned on, and a bare run is real provider spend — so `--selftest` also
asserts every plant clears the *strictest* reading by a stated margin, and
re-runs both halves across 64 seeds. Tuning a plant to land just the right
side of a threshold now fails offline at whichever seed exposes it, instead of
surfacing as an unwinnable client mid-run. `fixture.py` carries the measured
distances; the nearest baseline sits ~0.17 of a ratio clear of the closest
threshold, so the wobble is not where seed fragility comes from.

Client `c07`'s Meta Ads endpoint returns `401 AUTH_EXPIRED`. What the system
does with that client is measured, not prescribed.

## Scoring

Exact set comparison, no LLM judging: each client's reported `flagged`
campaign ids against ground truth, so a miss and an over-flag both count
against the run. `reason` text is recorded and never scored.

`protocol.py --selftest` proves that path against a synthetic flawless cycle
and then against a dropped client, a missed flag and an invented flag — each
must move exactly one counter.

## Protocol

Staging Orchestra, isolated context tree
(`colleague/usecases/agency_client_reporting/<run-id>/...`), never a real
assistant. `UNILLM_CACHE=false`, so every token is real inference. The driver
boots the brain standalone (same wiring as the ConversationManager sandbox),
issues the brief once, then drives the monthly wake through
`TaskScheduler.execute` with the delegate mechanics production uses for due
tasks. unillm's process-global hook meters every call into a per-phase ledger;
calls outside a phase window surface in a `background` bucket rather than
disappearing.

Deliveries posted during setup are scored separately from the metered month:
the brief asks for a schedule and never forbids running one immediately, so a
setup dry run is a fair reading of it — but it is not the first month, and its
reports must not divide the first month's cost.

**Each run is anchored to the pair it is actually going to compare.** The two
regimes disagree about what "last month" means when a task is fired ahead of
its schedule: a description-driven run reads its own activation, so a task
first activating 2026-09-01 reports 2026-08, while a stored entrypoint reads
the wall clock and reports the month before today. The fixture pins its
anomalies to one pair at a time, so before each wake the harness derives the
month that run will report from its regime, moves the plants there, and
re-derives and re-proves ground truth at that anchor. Both regimes are
therefore measurable in one cycle. `_window_alignment` still checks the
prediction afterwards, and a run that reported some third month yields no
figures at all — it looks like a clean sweep and is worth less than no
measurement.

Two related guards, because a wasted cycle costs about $30. Re-anchoring is
wrapped so a defect there degrades to the anchor already being served instead
of discarding a paid-for setup. And a phase that did real work while metering
zero LLM calls is labelled a missing measurement, not a cheap one — the
unillm hook has gone missing mid-run before, and the transcription block now
refuses to quote a cost from a phase like that rather than printing $0.0000.

## Run it

```bash
ACR_CHECK=true bash colleague/tracks/usecases/agency_client_reporting/run_unify.sh
bash colleague/tracks/usecases/agency_client_reporting/run_unify.sh
```

`ACR_CHECK=true` boots everything, prints the exact utterance and spends
nothing — always run it first. A bare run is real provider spend, about $30
for a two-wake cycle, so the launcher refuses four ways before starting one: an
argument (it takes none, and answers `--help`), the fixture port already bound,
another driver already running, and uncommitted changes under this directory.
The last is the track's contract, not tidiness — a cycle metered against
uncommitted code has no commit to transcribe a figure from, and code can be
edited underneath a 45-minute setup. `ACR_ALLOW_DIRTY=true` overrides it and
says so. `ACR_CHECK=true` skips all four, since it spends nothing.

Knobs (env): `ACR_RUNS` (default 1; 2 also measures whether the task
converges onto a stored entrypoint), `ACR_SEED`, `ACR_PORT`,
`ACR_PHASE_TIMEOUT_S`, `ACR_ORCHESTRA_URL`, `ACR_UNIFY_KEY`,
`ACR_USECASES_TSX`.

Before paying for any of that, three checks cost nothing:

```bash
python -m colleague.tracks.usecases.agency_client_reporting.fixture --selftest
python -m colleague.tracks.usecases.agency_client_reporting.protocol --selftest
python -m colleague.tracks.usecases.agency_client_reporting.replay_entrypoint
```

The third replays the newest committed run's stored entrypoint against the
fixture with the narrative call stubbed. It is how a fixture change is checked
against the artifact that has to keep working — but it measures a stored
function, not the system, so its flag count is never page-eligible.

Outputs land in `results/<run-id>/`:

- `results.json` — brief + digest, utterance, ground truth, task snapshots,
  every delivery verbatim, per-client scores, per-phase ledger totals
- `ledger.jsonl` — every LLM call (model, tokens, provider cost)
- `summary.md` — the phase table, the per-run table, and the transcription
  block naming which figures may go on the page and which may not

## Human protocol

Run `python -m colleague.human usecase agency_client_reporting` for direct
account-manager work. The verbatim page brief, fixture anchor and exact
campaign-set scorer are reused. Results include total active labour, labour
USD, and time and cost per drafted client report.
