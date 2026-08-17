# Track: teaching

**Walk through it once, then ask for it again.**

The invoice chase has two rules a person would mention while showing you and
never write down: a threshold that is not the obvious one (45 days, not 30),
and a vendor chased through their account manager rather than directly.
Neither is discoverable from the API.

| Scenario | |
|---|---|
| `week_31_taught` | The walkthrough. Any arm following instructions should get this right. |
| `week_32_replay` | The measurement. "Run the invoice chase for week 32" — nothing restated. |
| `week_33_corrected` | A third rule arrives as a correction after the first reminder has gone: don't chase anyone on a payment plan. Progress kept, remainder corrected. |
| `week_34_replay_after_correction` | The measurement for the correction. "Run the invoice chase for week 34" — nothing restated. |
| `untaught_control` | No walkthrough, ever. Establishes what the API alone yields. |

Weeks 33 and 34 are `interruption` × `teaching`: a colleague who is corrected
mid-task does not need telling again next week. The correction is keyed to
the first reminder (every reminder is held a few seconds so the second cannot
begin before it is in hand); week 33 scores that nothing on a payment plan
was chased *after* the correction and everyone else still was; week 34
scores the recomputed set with the rule applied, unprompted. An arm whose
continuation turn cannot be reached mid-run resolves UNSUPPORTED on week 33
— and its week 34 then reads as "never told", not as forgetting.

The control is what makes week 32 readable. If an arm scores the same on both,
its second-week success was inference, not retention — so the control is
expected to resolve `UNSUPPORTED` for everybody, and an arm that passes it
has told you its week-32 result means something different.

The fixture draws invoice ages per band rather than uniformly. A uniform draw
left both weeks with nothing between 31 and 45 days, which made the taught
threshold and the obvious one select identical invoices — a week that cannot
distinguish remembering from guessing.

```bash
python -m colleague.run teaching --arm unify
```

**The demonstration medium.** The original framing was learning from a
screenshare demonstration; this track is the text walkthrough. The frames
variant now lives in `screenshare`, with its own fixture and scorer.
