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
Scoring is containment: every part of the current value present, no stale
marker present.

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

## Not built yet

**Across a restart.** The same questions in a fresh process, so that only a
durable store answers. The scenario shape exists (`fresh_session: True`),
but the CM adapter keys its context tree to the run id, so a fresh session
would lose the week for a reason that is the adapter's and not the
product's. Pin the context tree across sessions in the adapter first, then
add the restart asks; until then a restart result would mismeasure.
