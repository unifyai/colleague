# ecommerce-trading-review

Measures the live page
[unify.ai/use-cases/ecommerce-trading-review](https://unify.ai/use-cases/ecommerce-trading-review):
a DTC brand's Monday trading review, pulled from Shopify, Klaviyo and Meta Ads,
posted to #trading before anyone is up.

## What the system is asked

The page's `brief` field, read out of `src/data/useCases.tsx` at run time and
passed through untouched, sha256 recorded. Alongside it: the fixture's
endpoints (standing in for three authorised connections) and the shape of the
hand-over POST (standing in for Slack). Nothing else — not which week to
report, not how to read "three weeks running" or "more than 20%", not which
metrics are moving.

## The fixture

`fixture.py` — stdlib-only, seeded, about a year of weekly history for one
brand, deterministic forever for a given seed.

Weekly series are harder to keep clean than the agency track's per-campaign
rows: bounded noise is not enough, because these rules are about *shape* over
several weeks. So the baseline is constructed rather than merely bounded.

| Rule (the page's words) | How the baseline can't trip it |
|---|---|
| repeat rate has fallen three weeks running | Repeat rate is a bounded level per position in a four-week cycle — rise, fall, fall, rise — so a baseline fall run is always exactly two. Nothing accumulates, so it cannot drift. |
| blended CAC risen >20% vs the four-week average | Ad spend is derived from new customers with a few percent of wobble, holding CAC inside ±10% of its own four-week average. |
| flow revenue drops while list size grows | List size and flow revenue are prefix sums of positive increments, so neither can fall. |

Three anomalies are planted in the reported week, one per rule. The
repeat-rate slide is planted to **begin two weeks earlier**, so the reported
week is the first week it qualifies — which makes "caught it the week it became
visible" measurable, rather than the page's "3 wks earlier" claim, which is a
comparison against how long a person would have taken and cannot be measured
this way.

`--selftest` sweeps the readings a reasonable person might take and
brute-forces all 54 baseline weeks in the history window, asserting none of
them trips anything, and that the week before the slide does not trip either.

### A bug this fixture already caught

The first version built the cumulative series by summing from a lower bound
that moved with the week index — a sliding window, not a prefix sum. Sliding
windows are not monotonic, so flow revenue fell on ordinary weeks while the
list grew, and rule C fired on six baseline weeks with no plant near them. The
selftest caught it before any provider spend. Worth knowing when adding a
track: for shape-based rules, assert the shape by brute force rather than
trusting the algebra.

## Scoring

A flag here is not per-entity — each rule concerns one brand-level metric — so
flags are identified by metric name from the brief's own vocabulary
(`repeat_rate`, `blended_cac`, `flow_revenue`) and compared as an exact set. A
metric outside that set is recorded as `flags_unrecognised` rather than counted
against the run, since the brief never enumerates identifiers. Reason text is
recorded, never scored. No LLM judges anything.

`protocol.py --selftest` proves that path against a flawless post, a missed
flag, a two-missed post, an unrecognised metric, and no post at all.

## Protocol

Staging Orchestra, isolated context tree, `UNILLM_CACHE=false`, brain booted
standalone, the Monday wake driven through `TaskScheduler.execute` with
production's delegate mechanics. One review per run, so the page-eligible cost
is per run rather than per client.

`ETR_RUNS` defaults to **2**, deliberately. The two execution regimes disagree
about which week is "last week" when a task is fired ahead of its schedule, so
a single run can land on a week where nothing is planted. Two runs guarantee
one aligned window, and the second is cheap once the task has settled onto a
stored entrypoint. Each run records the week it reported and the transcription
block refuses to emit any figure when that missed the plants — a misaligned run
looks exactly like a flawless zero-flag week.

Posts made during setup are scored separately: the brief asks for a schedule
and never forbids running one immediately.

## Run it

```bash
ETR_CHECK=true bash colleague/tracks/usecases/ecommerce_trading_review/run_unify.sh
bash colleague/tracks/usecases/ecommerce_trading_review/run_unify.sh
```

`ETR_CHECK=true` boots everything, prints the exact utterance and spends
nothing — always run it first.

Knobs (env): `ETR_RUNS`, `ETR_SEED`, `ETR_PORT`, `ETR_PHASE_TIMEOUT_S`,
`ETR_ORCHESTRA_URL`, `ETR_UNIFY_KEY`, `ETR_USECASES_TSX`.

Outputs land in `results/<run-id>/` — `results.json`, `ledger.jsonl`,
`summary.md`. If a phase table reads zero cost, that is the metering defect
described in the agency track's
[latest NOTE](../agency_client_reporting/results/2026-08-04T17-36-52Z-unify/NOTE.md),
not a free run: reconstruct from `GET /v0/credits/transactions?category=llm`
and cross-check against the balance delta.

## Status

Built and self-testing; not yet run against a live arm, and **do not start one
yet**.

As of 2026-08-05 the setup phase dies before it creates a task. The actor
web-searches Artificial Analysis and OpenRouter pricing to pick a model for its
own narrative step, that search's summarisation call returns whitespace instead
of JSON, litellm cannot parse it, and the exception aborts the whole task. It
failed that way twice in a row on the agency track for about $19 of provider
spend, and this brief drives the same actor down the same path.

Not reproducible against OpenRouter directly: both models return valid JSON in
`json_object` mode for a small prompt and for a 52k-token one, so prompt size
is not the trigger. Most likely `json_object` combined with tool calling — the
search loop's model returns empty content when it intends a tool call.

Run this once that is fixed, or with the web capability disabled and the change
disclosed on the page.
