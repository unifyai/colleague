# Pre-factoring baseline

This run used the build before unify commit `9f54cf012` ("Make shared
rules a first-class guidance concern"). Its storage reviews embedded the
escalation policy inside each of the three functions with no canonical
guidance entry, so the policy change had to rediscover and rewrite three
functions: 31 calls / 2.63M tokens / $10.13.

The factoring-enabled rerun (`2026-07-31T20-02-58Z-unify`) produced one
guidance entry ("Customer inquiry triage and escalation policy",
`function_ids: [0, 1, 2]`) with reviews 2 and 3 linking into it rather
than duplicating, and the change session followed those links: 13 calls /
1.02M tokens / $2.72 — 2.6× cheaper, and cheaper than the hermes arm's
change session — with the same 15/15 correctness. The slice-validation
run (`*-slice`) gated the prompt change before this full rerun.
