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
| `untaught_control` | No walkthrough, ever. Establishes what the API alone yields. |

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

**What this v0 does not do.** Dan's original framing was learning from a
screenshare demonstration, and this is a text walkthrough. Images are plumbed
as ordinary message content in unify and accepted by OpenClaw and OpenCode,
so an image-carrying variant is buildable — it needs synthetic screenshots
of a fake app, and a decision about hermes, which has no image path at all.
The retention question is the same either way; the demonstration medium is
what is missing.
