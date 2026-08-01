# Semantic triage

**Question:** when a recurring workflow contains a genuine judgment substep —
classifying free-text customer inquiries — what does each architecture's
steady state cost per firing, and how reliable is it?

This measures the functions/guidance blog's central efficiency claim
directly: Unify's design distills recurring work into a stored function
whose **control flow is frozen** and whose ambiguous substep is isolated in
focused `query_llm` calls (small, narrow prompts, injected into the function
execution environment). The expected steady state is a few thousand tokens
per fire. A `no_agent` cron script cannot classify language, so hermes's
natural steady state keeps an agent in the loop each fire — paying the full
agent boot before any classification happens — or hardcodes a model-API call
into a script, which is a legitimate outcome the meter records equally.

## Task

"Every hour, triage new customer inquiries into refund / bug / sales /
other and file the routed batch." The fixture (`fixture.py`) generates
seeded natural-language inquiries with golden labels, deliberately worded
with cross-category vocabulary (a *bug* report about the payment screen, an
*invoice* question that is not a refund) so classification requires reading
for meaning. Validated properties: a naive keyword classifier scores ~71%;
`gpt-4.1-nano` scores ~96%; the benchmark model should be near-perfect.
Golden labels are certain by construction (category chosen before text is
rendered). The sink is the cursor, so fires are timing-independent.

## Protocol

8 fires × 12 inquiries, no drift, no human. Identical utterance
(`protocol.py`), same metering as the other experiments (chained unillm
ledger / recording proxy, same pinned model), exact contract scoring plus
per-item accuracy against golden labels.

```bash
bash colleague/tracks/standing/semantic_triage/run_unify.sh
ST_PORT=8129 bash colleague/tracks/standing/semantic_triage/run_hermes.sh
.venv/bin/python -m colleague.tracks.standing.semantic_triage.plot
```

Headline graph: per-fire LLM tokens (log scale — the gap is orders of
magnitude) and per-fire classification accuracy.

## Measured results (2026-07-31, gpt-5.6-sol@openrouter)

![semantic triage](results/semantic_triage.svg)

Both arms delivered every batch with **100% accuracy on all 96 inquiries**.
The architectures diverged exactly as predicted, and the whole difference is
cost:

| arm | converged to | steady-state per fire | one-time cost |
|---|---|---|---|
| unify | stored function, frozen control flow, **one** focused `query_llm` call | **1 LLM call · ~645 tokens · $0.006 · ~10 s** | setup 635k + fire-1 distillation 821k |
| hermes | prompt-driven cron (`no_agent: false`) — full agent boot each fire | 5 LLM calls · ~21.5k tokens · ~22 s | setup 154k |
| openclaw | prompt-driven isolated cron (`agentTurn` payload) — agent turn each fire | 4 LLM calls · ~30k tokens · ~21 s | setup 84k |
| opencode | self-authored *custom agent* + cron spec, fired via its own declared command | ~8.8k-18.9k tokens · ~12 s | setup 115k-125k |

The opencode arm was run **three times** because its setup is bimodal: 2 of 3
runs produced a working automation (both then scored 8/8 at 100%), and 1
produced nothing at all after its attempt to install a launchd job was
blocked by OpenCode's own permission model. Conditional on setup
succeeding it is the second-cheapest arm per firing, because the agent
points its schedule at a narrow custom agent definition rather than the
full default context. See the `*-opencode` NOTE.md.

The openclaw arm (2026-07-31, added later the same day) also scored 100%
on all 96 inquiries — three architectures, zero scorer daylight — on the
cheapest setup and the most expensive steady state of the three; its
break-even against unify's distillation lands near fire 47.

Same request, same model, same perfect accuracy — **~33× fewer tokens per
firing** than hermes (~48× vs openclaw). Hermes's cheaper setup buys it the first ~2.5 days of hourly
firing; from fire 62 unify is cheaper forever, and by three days the gap
grows linearly (~21k tokens per fire, ~500k/day, ~15M/month for this one
automation). The judgment substep is what forces the contrast: hermes's
zero-token `no_agent` script mode cannot classify language, so its prose
architecture must re-boot the agent hourly, while the functions/guidance
split isolates the ambiguity into a single narrow prompt inside otherwise
deterministic code.
