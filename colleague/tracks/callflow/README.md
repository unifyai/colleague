# callflow — designed, not built

Hand the assistant a decision tree, ask it to call someone and follow it,
and score which leaf it reached.

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

## Adapter requirements — the reason it is not built

- **A callee** the arm can dial: a SIP/LiveKit endpoint the harness owns,
  answered by the persona (TTS out, STT in, the persona pool deciding what
  to say). This is the same transport `meeting` needs, on one leg.
- **Per-arm dialling**: `unify-cm` with a real comms path (`make_call` →
  Twilio conference + LiveKit SIP leg — the adapter currently stubs
  outbound); OpenClaw's `voice-call` extension pointed at the harness's
  number.
- **Utterance capture** on both legs with timestamps, for the hang-up check
  and the withheld-item check.
- **An `/outcome` contract** in the API doc, so an arm with no structured
  disposition still reports the leaf it believes it reached.

Build the callee once and `meeting` reuses it as a participant.
