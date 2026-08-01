# Measurement caveat — token/cost columns invalid

This first run had two harness defects, both fixed before the
`2026-07-31T09-43-51Z` run:

1. The LLM ledger hook was installed before `unify.init()`, which installs
   its own process-global unillm hook and overwrote ours — so every
   token/cost cell reads zero. The traffic was real (visible in debug logs)
   but unrecorded.
2. Phases closed at `handle.result()`, but post-run storage reviews detach
   from the handle. With no quiescence barrier between compressed runs,
   run 1's review landed mid-run-3 (`entrypoint None → 0` after run 3), and
   runs 1–3 all executed description-driven.

**What remains valid** — the behavioral columns, which independently
demonstrate re-derivation variance: three description-driven executions of
the identical task description produced two different week interpretations
(runs 1 and 3 delivered the in-progress week, run 2 the correct last full
week), while run 4, executing the stored entrypoint, was correct.
