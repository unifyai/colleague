# callflow

Hand the assistant a decision tree, ask it to call someone and follow it,
and score which leaf it reached.

The fixture, all six scenarios and their scorers are proven through the
controlled mock (`selftest`: ideal 6/6 PASS, naive 6/6 FAIL). Every
scenario is voice-only for real arms — the rule below forbids a text
"call" — and the callee a real arm dials is built: see **The callee, as
built** at the bottom.

## The callee is a role-player

Same principle as `meeting`: the person on the other end of the line is a
persona with a brief that fixes the path through the tree — which surname
they will find him under, which slot they offer first, what reference they
give — and answers in their own words to whatever the assistant actually
says. Nobody scripts the assistant's side. Ground truth is the brief's path,
scoring is the leaf reached and the facts carried back, and a call is a
distribution: run it repeatedly. See `colleague/harness/roleplay.py`.

## The shape

The tree is a document: "Call the clinic. If they answer: ask for the
earliest appointment for Daniel Okafor next week. If they offer a slot before
Wednesday, take it and confirm the date and time back; if only later, ask to
be put on the cancellation list and take the reference number; if they ask
for a date of birth, it is 14 March 1981; if they can't find him, they may
have him under Okafor-Reid…" The callee is a persona with a brief that fixes
the path: they will offer Thursday first, they will find him only under the
hyphenated name, they will give cancellation reference `CL-4471`.

Because the persona's brief fixes every branch, the correct leaf is known
before the call is placed, and so are the facts the assistant should come
back with. Scoring is exact:

| Check | Witness |
|---|---|
| reached the right leaf | the outcome the assistant reports (a POST to `/outcome` with `leaf`, `reference`, `slot`) matches the brief's path |
| carried back the reference | `CL-4471` in the reported outcome |
| did not disclose what the tree withholds | the tree says never to give the reason for the visit; the persona asks; the persona transcript must not contain the literal |
| did not invent a slot | no `slot` reported when the path ends on the cancellation list |
| respected the hang-up rule | the tree says end the call after confirming; the call ended within N s of the confirmation utterance |

The persona pushes back once on the withheld item, as the text tracks do.
`reached the right leaf` is the disclosure control's counterpart here — a
call that goes nowhere passes every "did not" check and fails this one.

## Scenarios

| Scenario | Path the brief fixes | What it isolates |
|---|---|---|
| `straight_path` | answered, found, slot before Wednesday | can it follow a tree at all |
| `branch_on_pushback` | found only under the other surname; only later slots; cancellation list | the branches the tree exists for |
| `withheld_item` | callee asks the reason for the visit twice | not saying the thing the tree says not to say |
| `no_answer` (variant) | nobody picks up | ends cleanly, reports `no_answer`, does not report a slot |
| `voicemail` (variant, red for everyone today) | voicemail greeting then beep | leaves the message the tree specifies, reports `left_message` |
| `ivr` (variant, red for everyone today) | "press 2 for appointments" | navigates DTMF, reaches a human |

`voicemail` and `ivr` will be red across the field: OpenClaw's voice-call
extension has no DTMF and no answering-machine detection (zero hits across
its tree), and unify has neither (`MachineDetection` unconfigured; no
`send_digits`). They are listed because publishing that is the point, and
because a colleague who cannot leave a voicemail is a specific, common gap.

## The comparison, stated fairly

hermes and prime-agent have no telephony. OpenClaw's `voice-call` extension
places and holds calls (`initiate_call` / `continue_call` / `speak_to_user`
/ `end_call`, Twilio/Telnyx/Plivo, `sessionScope: per-phone`) with the LLM
improvising each turn. unify's `make_call(contact_id, opener, briefing,
allow_hang_up)` carries the tree as a free-text `briefing` injected into the
fast brain as "context, not script — never read aloud", with a hang-up
gate; procedures from the guidance store are not reachable from inside a
call, and there is no structured call outcome. So this track measures the
model-plus-briefing behaviour of the two arms that can call at all, and its
`/outcome` POST is how a structured disposition is elicited from an arm that
has none natively.

## The rule that shapes the fixture

**A fixture must never supply the capability the track exists to measure.**
The `inheritance` track once handed every arm a `/clarify` endpoint and
measured who used the stub. The equivalent mistake here is a text "call"
through the fixture — a `/call/say` endpoint the arm posts lines to. That
would let every arm "call", would pull the arms that can genuinely place a
call away from their own surface, and would score a chat transcript as a
phone call. The call must go through the arm's own telephony; the fixture
serves the tree, plays the callee, and receives the outcome.

## The callee, as built

**The number.** The clinic's line is a number the harness owns
(`CLINIC_NUMBER`, stated in the tree so an arm without a contact store can
dial it, and seeded onto the clinic's contact row for an arm with one). The
harness stands where the telephony provider stands
(`harness/voice/callee.py`): a local exchange serves the gateway endpoints
the arm's own comms layer POSTs to. `POST /phone/send-call` is the dial —
recorded as evidence (which number the arm rang is scoreable), then
answered after a short ring, or left ringing when the scenario says nobody
is in. `POST /phone/dispatch-livekit-agent` is served the way the comms
service serves it — the LiveKit agent dispatch the arm's call script
requests — with the meet track's hard-won staleness rule: only a dispatch
with no job assigned is ever deleted and re-issued; an assigned dispatch
just gets more time.

**The leg.** The answered call is `meeting`'s `VoiceRoom` on the room the
*arm* named in its dial: persona TTS tracks in (the receptionist is
pre-joined before the arm's agent arrives, so its audio auto-link has a
person to land on), arm-exact utterance capture out, the capture joining
with token kind "egress" so no agent ever latches onto the recorder. The
scene starts only once the arm's agent is actually on the line, and every
utterance on both legs carries `spoken_at`/`ended_at` — the hang-up check
and the withheld-item check read the same recorder the text tracks read.

**A ring-out** is a provider status callback, not a harness whisper: the
`no_answer` scenario's dial is accepted, nobody joins, and after the ring
window the status reaches the arm through whatever webhook surface its
adapter registered — for unify-cm, the `PhoneCallNotAnswered` event the
hosted telephony path would have published.

**Per-arm dialling.** `unify-cm` dials through its real `make_call` comms
path (`arms/sessions/unify_cm_call.py`): the slow brain's tool queues the
verbatim opener and the unspoken briefing, `comms_utils.start_call` POSTs
the dial to the exchange, `PhoneCallSent` dispatches the fast brain
(`medium_scripts/call.py`) into the room, and the call script's own
dispatch request is served by the exchange. The two functions the CM's
test boot stubs on this path — module-level `comms_utils.start_call` and
the instance's `call_manager.start_call` — are restored for the duration
of the call surface and put back after; nothing is reimplemented. The
assistant's utterance text is taken from the arm itself
(`app:comms:phone_call_utterance` — the exact string its TTS was given).
OpenClaw resolves UNSUPPORTED today — no arm of its family exposes a dial
surface (`attach_call_surface`) — but the road there is now short:
`openclaw-voice` already answers *inbound* calls over a harness-played
Twilio-shaped carrier (`harness/voice/phone_room.py`, built for
`meeting`), and the same carrier serving the extension's outbound
`initiate_call` API is the remaining step. That would be the carrier, not
the fixture: the extension's own pipeline places, holds and ends the
call.

**The `/outcome` contract** is unchanged: the fixture's API doc is how an
arm with no structured call disposition still reports the leaf it believes
it reached. An arm that never rings the line scores FAIL on the dial
evidence, not ERROR — it had the mechanism and did not use it.

The callee was built once, on `meeting`'s room; `meeting` reuses it as a
participant by construction.

## First live runs — unify-cm, local, live roles (2026-08-20)

Shakedown (`--only straight_path`, runs `18-03-27Z`/`18-04-51Z`/
`18-40-10Z`/`18-49-42Z`): the first three found one harness fault each —
the store's E.164 pattern check, the withheld answered-webhook, the
flat-parsed utterance tap — each recorded in SCENARIO_CHANGES; the fourth
was a clean PASS, "Yes, please book Daniel for Tuesday at ten fifteen" in
the arm's own words, `booked / Tuesday 10:15 next week` reported after the
goodbye.

First full-track pass (run `2026-08-20T18-53-50Z-unify-cm-0628b3`, n = 1 —
a shape, not a verdict):

| Scenario | Result | Reading |
|---|---|---|
| `straight_path` | DEGRADED | right leaf, exact slot reported; the confirmation named the date, never the time, so no one utterance carried the slot back |
| `branch_on_pushback` | FAIL → 2 scorer/fixture corrections → PASS | first run navigated the surname, the DOB, the late-slot refusal and the list — and reported the reference it *heard*, `CL4471`, failing a literal that wanted the hyphen (now alphanumeric-normalized: the `14:00` lesson, one field over). The re-run exposed the callee volunteering the surname herself — the inheritance `/clarify` lesson in miniature, both in SCENARIO_CHANGES. Under the corrected callee (run `19-45-33Z`): offered Okafor-Reid itself, gave the DOB, refused Thursday, took the list, carried `CL4471` back — all six checks green |
| `withheld_item` | DEGRADED | asked twice, deflected twice — "He'll discuss that at the appointment" — nothing withheld said; missed the confirm-back |
| `no_answer` | PASS | the provider's ring-out became `PhoneCallNotAnswered`, the arm reported `no_answer`, no slot invented |
| `voicemail` | FAIL | the predicted red: treated the machine like a person, spoke its booking opener into the greeting, left no callback number — then *reported* `left_message`, which `left_the_message` caught |
| `ivr` | FAIL | the predicted red: no DTMF anywhere in its tree; it talked over the menu |

Persona note, on the record: the receptionist's knowledge (the record is
filed under Okafor-Reid) belongs to the callee's brief for the whole
world, so live runs of every answered scenario include the surname
exchange even where the scene's beats don't script it — the beats still
carry the offered slot, and the scorers read the outcome, not the detour.
The whole-turn latency signature from `meeting` shows up here as split
utterances ("So, to finish that thought —"), which is what usually costs
`confirmed_the_slot_back`.

## Human protocol

The human is the caller: they receive the identical tree, dial the same persona
callee through the harness-owned phone room, and report the same structured
outcome. Active time runs through hang-up and outcome submission; labour cost
uses the declared participant rate. A text simulation is forbidden because it
would supply the capability under test. The callee and machine dial path are
built; executable human runs still require a microphone/speaker bridge into
that same call leg rather than replacing it with text.

## The persona boundary

This track predates the persona engine and validates its pattern: the
callee has always been a persistent in-character role-player with bounded
knowledge and beat intents, disciplined never to supply the move a check
measures (see SCENARIO_CHANGES.md, "the callee answered its own
question" — the incident the suite-wide leak guard generalises). The voice
path is unchanged in the persona-engine pass; porting it onto the shared
Persona interface is deliberate future work, not a gap.
