# Reading this arm's fires table

Three independent prompt-driven cron jobs, one per request, same shape as
the other OpenClaw arms. Two findings, one in each direction:

1. **The policy change is the cheapest of the three arms by ~7×** — 5
   calls / 142k tokens / 54 s (unify 1.02M after its guidance-factoring
   fix; hermes 1.14M). The agent's own cron store is small and legible to
   it: it listed its three jobs, rewrote all three payloads
   (`artifacts_changed` names all three cron ids), and was done. Digests
   and audits scored 1.0 on every post-change round, so the new $250
   threshold genuinely propagated.
2. **It is the only arm that dropped exactness: 10/15 fires fully exact**
   (unify 15/15, hermes 15/15). None of the misses are propagation
   failures — triage wobbled pre-change too (0.9, 0.8) and after (0.9,
   1.0, 0.4), and round 1's digests fire broke the delivery contract on
   its bootstrap run. Every fire is a fresh agent turn re-deriving
   judgment over the batch, so item-level classification variance never
   freezes out; the worst fire (0.4) was also the cheapest (2 calls),
   a turn that plainly skimped. Contrast unify's frozen control flow +
   one focused `query_llm` per item batch (1.0 every round) and hermes's
   tighter per-job prompts (1.0 every round in the definitive run).

Steady state for the family is the most expensive of the arms (~80k
tokens/round vs hermes ~57k, unify ~2.2k). So openclaw wins the change
axis outright, loses the steady axis, and pays for per-fire freshness
with the suite's only accuracy variance in the absence of any drift.
