# recall

Facts told in passing over eight days, asked about on the ninth.

`custody` and `teaching` ask about something said a turn or two ago. This
track asks after a working week of ordinary messages, in which three of the
facts changed: the offsite moved twice, a vendor contact left, a deploy
window shifted. The right answer is the newest value, and none of the old
ones.

| Question | Current | Replaced |
|---|---|---|
| `ask_offsite` | Leeds | Bristol, Cardiff |
| `ask_trellis_contact` | Ekdahl | Lindqvist |
| `ask_deploy_window` | Wednesday 11:00 | Thursday |
| `ask_portal_manager` | Varga | — |
| `ask_travel_code` | 2210 | — |
| `ask_priya_cover` | Haddad | — |
| `ask_board_and_bucket` | Brandt + ledger-exports-7 | — |

The four stable questions are retention controls, declared in
`selftest.py`. An arm that gets a superseded question wrong and the stable
ones right did not forget — it recalled the wrong version. That is the
failure this track is for, and the controls are what let a reader tell it
apart from an arm that simply lost the week.

## How it runs

One session across the track (`SESSION_SCOPE = "track"`). Eight `day_N`
turns from Daniel, each `continue: True`, with nothing to do; then seven
`ask_*` turns. Every arm answers Daniel through its own reply channel, so
there is no fixture endpoint and nothing to route — the fixture is bare.
Scoring is containment: every part of the current value present, and no
stale value *instead of* it. A reply that gives the current value and names
what it replaced is correct — a containment test cannot tell explanation
from confusion — so the old names are recorded as evidence, not scored.

**Cost per answer** is not scored but is reported: the arms already produce
a per-turn ledger (`unify_ledger.jsonl` / `llm_segments` in the run
artifacts for the CM arm; the recording proxy for the others). Read the
`ask_*` turns' token counts against each other — an arm that carries the
whole week in its prompt pays for it on every question; an arm that
retrieves pays for the retrieval.

## What to expect

This is not a track where one architecture is expected to sweep. OpenClaw's
memory has a supersession key and write-time provenance; unify has
`supersede_knowledge` and embedding search over typed claims; hermes keeps
two flat files that are always in the prompt. Any of those can get the
newest value right. What differs is what it costs by day eight, and whether
the old value is genuinely gone or merely outranked.

## Across a restart

`ask_after_restart` re-asks the whole week in one message, in a fresh
process (`restart: True`): the session is torn down and a new one boots
over the same durable world. The runner hands a restart session the run's
own id, so an arm whose store is keyed by it — the CM's context tree, the
mock's durable store — reattaches, while an arm that carried the week in
its prompt has nothing. `fresh_session:` remains the opposite shape, a
clean store for control scenarios, which is why restart is its own key.
Scoring is the ask scoring across every question at once: each current
value contained, no stale value standing in for a missing one. A restart
scenario belongs after the turns it must remember, and nothing may use
the track's shared session once the restart has booted over it.

Recorded run `2026-08-19T15-35-52Z-unify-cm-71152d`: every in-session ask
passed; after the restart six of seven came back current — including both
other supersessions, the twice-moved offsite and the shifted deploy
window — and the Trellis contact came back as the replaced name. In one
process the newest value outranked the old; across a restart the old one
resurfaced, which is precisely the distinction this variant exists to
catch.

## Human protocol

Run `python -m colleague.run recall --arm human`. The same participant receives
the compressed eight-day sequence and may use persistent notes, the declared
aided-human baseline. Current/stale containment, cost per answer, active time
and labour cost are recorded.
