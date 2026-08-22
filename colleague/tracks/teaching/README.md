# Track: teaching

**Walk through it once, then ask for it again — for six weeks.**

The invoice chase has two rules a person would mention while showing you and
never write down: a threshold that is not the obvious one (45 days, not 30),
and a vendor chased through their account manager rather than directly.
Neither is discoverable from the API. The walkthrough also asks for one
thing on the way: show me who you are about to remind the first time, then
never ask again.

| Scenario | |
|---|---|
| `week_31_taught` | The walkthrough. Any arm following instructions should get this right — and should raise the preview once, through its own channel, before the first send. |
| `week_32_replay` | The first measurement. "Run the invoice chase for week 32" — nothing restated. |
| `week_33_corrected` | A third rule arrives as a correction after the first reminder has gone: don't chase anyone on a payment plan. Progress kept, remainder corrected. |
| `week_34_replay_after_correction` | The measurement for the correction. "Run the invoice chase for week 34" — nothing restated. |
| `week_35` | One rule amended in one sentence — Bergen Chemical's account manager has changed — then "run it for week 35". The threshold and the payment-plan rule are not mentioned and must not move. |
| `week_36` | Unattended again; the amendment and both untouched rules must hold. |
| `untaught_control` | No walkthrough, ever. Establishes what the API alone yields. |

Weeks 33 and 34 are `interruption` × `teaching`: a colleague who is corrected
mid-task does not need telling again next week. The correction is keyed to
the first reminder (every reminder is held a few seconds so the second cannot
begin before it is in hand); week 33 scores that nothing on a payment plan
was chased *after* the correction and everyone else still was; week 34
scores the recomputed set with the rule applied, unprompted. An arm whose
continuation turn cannot be reached mid-run resolves UNSUPPORTED on week 33
— and its week 34 then reads as "never told", not as forgetting.

Weeks 35 and 36 are where an amendment and a regression test share a
scorecard on purpose. The seed puts invoices at 33 and 38 days overdue in
week 35 and at 34 and 35 in week 36 — inside the band the taught threshold
excludes and the obvious one includes — so an arm that takes the new account
manager on board and quietly drifts back to thirty days is caught in the same
week (`amendment_applied` passes, `untouched_rules_kept` and
`exact_recipients` fail). Forgetting the payment-plan rule shows the same
way: the vendor on a plan is over the threshold in both weeks.

The preview is scored on presence, never on prose: a clarification raised
through the arm's own channel during week 31 that names someone it is about
to remind, and no clarification at all in the unattended weeks. Daniel
answers the preview as a persona ("looks right — go ahead"); the channel
blocks until he does, so "before the first send" is the order the arm keeps
rather than a timestamp the harness compares.

The control is what makes the later weeks readable. If an arm scores the same
on both, its second-week success was inference, not retention — so the
control is expected to resolve `UNSUPPORTED` for everybody, and an arm that
passes it has told you its week-32 result means something different.

Cost per week is reported from the ledger (`llm_segments` in the unify run
record, per turn) and never scored.

The fixture draws invoice ages per band rather than uniformly. A uniform draw
left both weeks with nothing between 31 and 45 days, which made the taught
threshold and the obvious one select identical invoices — a week that cannot
distinguish remembering from guessing.

```bash
python -m colleague.run teaching --arm unify-cm
```

**The demonstration medium.** The original framing was learning from a
screenshare demonstration; this track is the text walkthrough. The frames
variant now lives in `screenshare`, with its own fixture and scorer.

## Human protocol

Run `python -m colleague.run teaching --arm human`. Simulated weeks remain
compressed; the same participant receives the walkthrough, correction and
amendment. Notes persist, while the untaught control gets a fresh workspace.
Every week records active labour and cost beside the exact recipient score.

## The persona boundary

Daniel listens on every channel: the week-31 preview counts whether it was
raised through the blocking hook or as an ordinary message he answered, and
`unattended` now means the arm needed nobody — no blocking question, no
message a person had to answer with content. A status report Daniel read
silently keeps a week unattended; a go-ahead he had to give does not (his
brief labels approvals `restated`: the walkthrough already said send them).
