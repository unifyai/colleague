# Intermediate run — fixed build, before the diagnostic probe

This run used the build with the four `5fb19164d` fixes but **without** the
repair loop's `run_diagnostic_probe` (added in `54987ca06`). The repair
worked but was blind — its only evidence was the failing function's own
validation messages — so converging on the field rename took four
fire-by-fire attempts (fires 5–8 lost, recovered at fire 9): 6/10, 1.74M
tokens, fully autonomous.

The probe-equipped run (`2026-07-31T13-24-15Z-unify`) is the current
result: the fire-5 repair observed the live API, fixed the function in
place in one attempt ($0.18, 82s), and delivered within the same run —
10/10 with zero-token fires either side of the blip.
