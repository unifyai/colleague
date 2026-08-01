# Pre-fix run — kept as the before/after baseline

This unify arm ran on the build **before** commit `5fb19164d` ("Fix
symbolic-entrypoint drift recovery") and is the run that exposed the four
defects that commit fixes:

1. The repair loop refused to adapt to the renamed field twice, treating the
   task description's input details as inviolable contract ("Unable to
   repair without changing the task contract").
2. The `add_functions` tool schema silently dropped `overwrite` (signature
   derived through the `functools.wraps` chain to the abstract base), so
   repairs could only delete-and-re-add, minting new function_ids and
   dangling the task entrypoint.
3. Post-run reviews attached function ids that did not resolve at execution
   time ("Entrypoint function_id 1/2 not found"), failing every later wake.
4. Description-driven fires 7 and 9 treated the recorded input spec as
   authoritative, declared "failed safely" no-ops, and reported completion —
   feeding broken executors to the review.

Outcome here: 4/10 correct fires, 2.89M tokens, $8.24, no recovery. The
fixed build's rerun (`2026-07-31T11-54-41Z-unify`) recovered autonomously:
6/10, 1.74M tokens, $6.47, back to zero-token correct fires by fire 10.
