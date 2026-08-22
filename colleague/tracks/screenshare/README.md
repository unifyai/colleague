# screenshare

Watch someone do it on their screen, then do it on yours.

Daniel shares his screen and does four things on his ops board: creates a
ticket, assigns it, tags it, closes an old one. The fixture renders a frame
of his screen after each step — the board as it now looks, and the action he
just took shown the way an application shows it, as a toast at the bottom.
The request carries the frames and says "do the same on your board". It
does not say what he did.

| Scenario | Input | Expected |
|---|---|---|
| `follow_the_share` | five frames, in order | B's final state equals what the demonstration produces; A untouched |
| `follow_the_text` | the same four steps in words | same — the control |

Six checks, all on the final state of the assistant's own instance (`/b`)
and the recorder: the new ticket exists once with the right priority, it is
assigned to Meera, it carries the tag, the old VAT query is closed, nothing
else changed, and Daniel's instance (`/a`) received no mutation at all. The
last is scored separately because acting on the demonstrator's screen
instead of one's own is a distinct confusion, not a bad reproduction.

The text control establishes what the API and the words alone yield, so the
frame scenario reads as "could it see" rather than "could it use the API".

## Frames

Rendered by `colleague/harness/frames.py`: a 5×7 bitmap font at 2–3× scale,
a framebuffer, and a PNG encoder — the standard library and nothing else, so
a third party reproduces the same pixels forever. Uppercase, monospaced,
900×420. That is a deliberate floor: if a vision model cannot read a
15×21 px block capital it cannot follow a screen share, and the track should
say so.

The frames are the only place the four actions are described. The scenario
text, the roster and the API doc name none of them; the fixture must not
contain the answer to the question its scenario asks.

## How frames reach an arm

`begin(..., images=[paths])` is part of the session contract. An arm whose
driver has no way to attach an image raises `Unsupported`, and the scenario
resolves to UNSUPPORTED — reported in its own column, never as a failure to
look. Today:

| Arm | Path |
|---|---|
| `unify-cm` | the CM's own screenshot buffer, source `user`, attributed to the sender and paired with the message — the same path a shared screen takes from the fast brain |
| `hermes-tui` | raises: no image path in the driven surface (`accepts_images=False`) |
| `openclaw-gateway` | images travel as chat.send attachments |
| `opencode` | raises: the driver has no attachment path yet, though the product accepts images — an adapter gap to close, and stated as one |
| `prime-agent-rpc` | images travel on the prompt |
| `mock` | receives the paths; the scripted plan acts on the demonstration by construction |

The `unify-cm` path is wired but has not yet been exercised against a live
run; the first live sweep should confirm the frames appear in the slow
brain's screenshot context before any number from this track is read.

## What this measures, stated fairly

Peer screen-share ingest is absent in every comparison harness at HEAD
(hermes has no screen-share path at all; OpenClaw's `screen` tool is
Control-UI layout and cannot read pixels; prime-agent has no capture). All
three can drive their *own* desktop or browser. So the interesting cell is
not "unify versus nothing": it is whether the arm that has both halves — see
a peer's screen, act on its own machine — actually joins them, which
unify's own prompt rules push against ("respond to what they said, not what
you see"). A loss here would be a finding about the product, and it belongs
in the results.

"Own machine" is stood in for by an HTTP instance the assistant alone acts
on. The demonstration was done in a UI; the reproduction goes through an
API. That gap — UI seen, API used — is part of what understanding a share
means, and it is deliberate. A later variant can put a real browser on the
assistant's side and score the same final state.

## Human protocol

Run `python -m colleague.run screenshare --arm human`. Attached frames are
listed in the workbench and `/open N` opens one in the system viewer. The same
final-state and demonstrator-untouched checks apply, with active time and
labour cost recorded.

## The persona boundary

`follow_the_share` meets a Daniel who will not narrate the demonstration:
the four steps exist only in the frames, and a stand-in who typed them out
on request would collapse the scenario into its own text control — the
leak guard voids the cell (`INVALID`) if he does. In `follow_the_text` he
literally said the steps and may restate them; the swap is scenario-scoped
(`persona_overrides`).
