# This run does not cleanly measure policy propagation — read the breakdown

Headline counters say 4/15 exact. **Do not quote that as an OpenCode
capability result.** The per-automation breakdown shows the number is
dominated by two things that are not propagation:

| automation | built at setup? | fire mode | outcome |
|---|---|---|---|
| triage | **no** — setup exited 0 having written nothing | wake_prompt | 0/5, nothing ever delivered |
| digests | yes (agent + command, correct content) | command:support-digest | 0/5 delivered — see below |
| audits | yes (agent + command) | command:escalation-audit | **4/5 exact** |

**triage** repeats the setup failure characterized in the semantic_triage
arm (2 of 3 setups produce an automation; this was a third case of the
failing mode), so a third of this experiment never had an automation to
fire.

**digests** is the subtler one, and it is not a fault in the artifact. The
command the agent wrote is correct — it reads `/digests/last`, fetches
inquiries after that cursor, and correctly declines to POST when there are
none. At every measured fire it found none: by then its cursor had already
advanced to the end of the released stream, so the digests it did produce
landed outside the harness's per-fire scoring windows (the policy-change
turn is the likely consumer, since it runs outside any fire window). The
automation worked; the harness measured the wrong intervals for it.

**audits** is the only automation this run actually measures, and it
scored 4/5 exact, with the policy change reaching it: the change session
(183k tokens) rewrote both existing command files, and post-change audit
fires honored $250.

Cost figures that are still valid, because they are ledger sums rather
than scored deliveries: setups 475k tokens across the three requests,
policy change 183k, steady state ~96k per round for the family — the most
expensive per-round figure of any arm in the suite, driven by every fire
being a fresh agent turn plus this arm installing `node_modules` into its
workspace.

To make this experiment conclusive for OpenCode it needs a rerun in which
all three automations build, plus a harness change so an automation that
legitimately has nothing to do is scored as such rather than as a missed
delivery.
