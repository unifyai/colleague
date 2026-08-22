# usecases

Every other track in this repo asks what a class of architecture does. This
one asks a narrower and more awkward question: **are the numbers on our own
marketing pages true?**

[unify.ai](https://unify.ai) publishes 19 use-case pages. Each describes a
workflow a droid runs, and each carries a `results` array — a cost, a
duration, a count. The workflows were always real product mechanics, but the
figures were composites: plausible, disclosed as illustrative, and not
measured. This track replaces them one page at a time with figures produced
by an instrumented run, and commits the ledger that produced each one.

A page's numbers are only as good as the run behind them, so the run lives
here rather than in the marketing repo: same fixtures, same per-phase LLM
ledger, same recomputed ground truth as the comparison tracks, and readable
by anyone who wants to check the arithmetic.

| Page | Status |
|---|---|
| [`agency_client_reporting`](agency_client_reporting/) | measured |
| the remaining 18 | composite |

## The contract

A figure may appear on a page only if it can be read off a committed
`summary.md` transcription block. Three rules follow from that, and they are
the whole point of the track:

1. **No replacement invention.** If a run does not produce a number, the
   claim comes off the page — it does not get a nicer estimate.
2. **The measured regime is the honest one.** Costs are transcribed from the
   first month, description-driven, because that is the month every customer
   actually has. A converged run (a stored entrypoint, near-zero tokens) is
   cheaper and is recorded in the ledger, but quoting it as typical would
   describe a steady state nobody has yet reached.
3. **What was not measured stays disclosed.** The scenario — the agency, the
   client names, the "two days of an account manager" it replaces — remains
   illustrative, and the page says so. Measuring a run does not turn its
   surrounding story into a case study.

## Adding a page

### 1. Fixture

`fixture.py`, stdlib-only and seeded, so a third party reproduces the same
data forever. It must serve the systems the page names, and:

- **Plant the page's own rules.** Read the `plays` and `brief` fields and
  plant exactly the anomalies those rules describe — nothing more.
- **Generate baselines inside safe zones**, bounded well away from every
  threshold, so a correct system's flag set is the planted set and never an
  artifact of noise.
- **Include the failure path the page claims.** If the page says it stops and
  asks when a connection dies, one account's connection has to actually be
  dead.
- **Recompute ground truth from the served data**, never from the generator's
  intent, and `selftest` it under a sweep of the tolerance choices a
  reasonable reader might make. If the flag set moves when "held steady"
  shifts from 0.95 to 1.00, the fixture is measuring its own thresholds.

### 2. Protocol

`protocol.py` reads the page's `brief` **out of `useCases.tsx` at run time**
and records its sha256. Nothing paraphrases the brief; a page edit that
changes the ask changes the digest, and the old figures stop being about the
current page.

Exactly two things may be added alongside it:

- **Connections** — where the fixture's endpoints are, standing in for the
  OAuth connections the brief says to connect.
- **A hand-over shape** — a POST contract carrying the artifacts the brief
  asks for plus the machine-readable fields the scorer needs.

Nothing else. Not the month, not the entity list, not the reading of the
page's own thresholds, not what to do about the broken connection. Everything
a human would have to work out is the measurement. Scoring is exact set
comparison — no LLM judging anywhere in the path.

`protocol.py --selftest` proves the scorer against a synthetic flawless
cycle, then against a dropped entity, a missed flag and an invented flag, so
a counter that never moves is caught before a run is paid for.

### 3. Run

`unify.py` + `run_unify.sh`, cloned from this page's pair. The driver boots
the brain standalone against **staging** Orchestra in an isolated context
tree, issues the brief once, then drives the schedule through
`TaskScheduler.execute` with the delegate mechanics the production
ConversationManager uses. `UNILLM_CACHE=false`, so every token is real
inference.

Always `ACR_CHECK=true` first: it boots everything, prints the exact
utterance, and spends nothing.

### 4. Transcribe

`summary.md` ends with the eligible figures and where each came from. Copy
them into the page's `results` array, swap `COMPOSITE_DISCLOSURE` for the
page's own measured disclosure, and link the run.

Claims about the human baseline ("two days of an account manager") are not
measurable here and should leave the `results` array rather than acquire a
fake denominator.

## Human protocols

Both built pages support the same direct, measured human protocol:

```bash
python -m colleague.human usecase agency_client_reporting
python -m colleague.human usecase ecommerce_trading_review
```

The participant completes the work directly against the unchanged page brief,
fixture and exact scorer. If work repeats, the next occurrence is presented to
the participant again with their notes and experience retained. Active seconds,
declared hourly rate, labour cost, elapsed time and per-output cost accompany
the existing metrics.

## The persona boundary

The owner's clarification answers now come from an owner persona under the
same information bound the old scripted constant enforced: his brief and
his own delivered messages are everything he knows, he never adds
information, and asked anything he points back and says go ahead (label
`repointed`; the scripted fallback is the old constant, unchanged, and is
what deterministic runs use). Persona spend lands in its own
`persona_ledger.jsonl` and is reported as `persona_tokens` /
`persona_exchanges`, never in the arm's columns.
