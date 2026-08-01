# Reading this arm's fires table

OpenClaw's prompt-driven cron (agent turn per fire) recovered from the
schema drift **autonomously — 9/10, no human** — and the shape of that
recovery is the finding:

1. **Fire 5 (first drifted) delivered nothing.** The job payload the agent
   authored at setup pins the old field name and instructs "on fetch or
   validation failure, do not POST", so the turn validated, found
   `unit_price_cents` missing, and correctly declined to deliver garbage.
2. **Fire 6 adapted and caught up.** With a model in the loop every fire,
   the next turn investigated the live payload, used the renamed field,
   and delivered the cursor-pending range (fire 5's missed orders
   included) exactly — which is why one fire is lost rather than six
   (hermes-alone flatlines at 4/10 because nothing ever looks again).
3. **The artifact never heals.** The cron payload was byte-identical after
   fire 10 — still describing `unit_price_cents` — so every post-drift
   fire re-discovers the rename from scratch: per-fire cost roughly
   2.5×es (≈16k → ≈40k tokens, 2 → 4-5 calls) and stays there. The
   adaptation is paid per fire, forever, instead of once.

Contrast across arms: unify repaired its stored function **in place**
(10/10, one $0.18 blip, then back to zero marginal); hermes's zero-token
script died silently (4/10 alone, 8/10 only after a 743k-token
human-initiated fix); openclaw absorbed the drift in-loop (9/10 alone) at
a permanent ~2× per-fire tax. Total for the 10-fire series openclaw is
cheapest (~0.40M vs 1.42M/1.51M) — at this hourly cadence its post-drift
slope (~40k/fire) hands the lead back to unify's flat line within ~28
more fires.
