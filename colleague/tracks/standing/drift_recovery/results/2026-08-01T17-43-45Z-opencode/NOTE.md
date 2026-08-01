# Reading this arm's fires table

OpenCode produced a standalone stdlib script (`process_orders.py`) and
nothing else, so its steady state is genuinely **zero tokens per fire** —
and structurally identical to the hermes arm's: with no model in the loop,
nothing observes a failure.

- **8/10 with a human, 4/10 without.** Fires 1–4 exact at zero cost. The
  field rename broke the script, fires 5 and 6 delivered nothing, and the
  harness played the same operator move as the hermes arm — one
  natural-language "it's been failing, fix it" message. That fix session
  cost 15 calls / 155,461 tokens and repaired the script correctly; fires
  7–10 were exact and free again, catching up the pending cursor range.
- **Cheapest total of any arm by a wide margin**: 302,591 tokens for the
  whole series (hermes 1.42M, unify 1.51M, openclaw 0.40M), because both
  its setup and its fix session are an order of magnitude cheaper than
  hermes's equivalents while buying the same outcome.
- **Same failure mode as hermes, at a quarter of the price.** Without the
  operator it flatlines at 4/10 forever, exactly as hermes does. This is
  the clean architectural pairing in the suite: script-based steady states
  (hermes, opencode) are free per fire and cannot self-heal; model-in-loop
  steady states (unify's repair path, openclaw's agent turn) recover
  unattended and cost something to do it.

Fire mode was `script:process_orders.py` throughout, per the firing rule
fixed before the run. Note this arm never registers a schedule of its own
— the harness supplies the wake (see the driver docstring), so the outage
is a property of the artifact, not of a missed trigger.
