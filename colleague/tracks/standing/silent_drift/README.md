# Silent drift

**Question:** `drift_recovery` renamed a field, and the arms that had a model
in the loop noticed because their code threw. What happens when the API
keeps every field name and changes what a field *means* — so nothing throws,
the automation keeps running, and the numbers it delivers are simply wrong?

This is the experiment the verified-function lifecycle exists for. A stored
function that trusts the description will keep executing and keep POSTing.
The only ways to score above zero from fire 5 on are to notice — because a
post-condition on the result no longer holds, because a verifier reading the
data against the description objects — and either repair or stop and say
so.

## Two variants, one at a time (`SD_VARIANT`)

| variant | before fire 5 | what a trusting implementation does |
|---|---|---|
| `units` | `amount` (int, minor units) is served as a float in major units: `1999` → `19.99` | sums floats a hundred times too small; every total is plausible and wrong |
| `page` | `/orders`, described as returning every pending order (never more than 100), starts capping at 50 | one fetch still returns rows; the batch covers 50 of the 80 pending and the cursor falls behind forever |

Ground truth is computed from the generator and unaffected by either.

## Protocol

- 10 fires, `ORDERS_PER_FIRE = 80` released before each; drift applied
  before fire 5. The utterance (`protocol.py`) describes the pre-drift API
  exactly, and — like every experiment in this family — tells the assistant
  how to hold: POST `HOLD: <reason>` to `/owner/notify` and deliver nothing
  when a run's data does not match the description or its numbers cannot be
  trusted.
- Unify arm: no human intervention. Whatever verification, repair or hold
  the runtime does is the result. A run the runtime holds natively (its own
  owner-facing "Holding …" message) is recorded `via="native"` and scores as
  held.
- CLI arms: after 2 consecutive non-correct fires the harness plays the
  operator once, as in `drift_recovery`.

## Scoring, per fire

| outcome | score | means |
|---|---|---|
| correct | 2 | exactly one batch, every field exact — integers, not floats that happen to be equal |
| held | 1 | no batch, and the owner told why (hold marker on the fixture channel, or a native hold) |
| wrong | 0 | anything else — wrong totals, a partial batch, two batches, or nothing and no word |

Held sits below correct on purpose (see `DESIGN.md`, non-negotiable rule
8). Tokens per fire are reported by purpose — planning / verification /
repair for the unify arm, all planning for the proxy-metered arms.

## Outputs

`results/<run-id>-<variant>-<arm>/` with `results.json`, `summary.md`, and
the raw ledger. `plot.py` renders `silent_drift_<variant>.svg`: an outcome
strip per arm and tokens per fire by purpose.

```bash
SD_VARIANT=units bash colleague/tracks/standing/silent_drift/run_unify.sh
SD_VARIANT=page  bash colleague/tracks/standing/silent_drift/run_unify.sh
SD_VARIANT=units bash colleague/tracks/standing/silent_drift/run_hermes.sh     # also run_openclaw.sh, run_opencode.sh
.venv/bin/python -m colleague.tracks.standing.silent_drift.plot
```

## Measured results

Not yet run. The honest expectation for the pre-verification unify build was
a loss on both variants — the stored function keeps delivering — and that
is the comparison the verified build is measured against.
