# Human testing

Every Colleague benchmark has a human-solvable primary outcome. Humans and
agent harnesses receive the same facts and are scored against the same
deterministic ground truth. The interface may be human-native — a workbench,
an image viewer or a call — but it must not add information or an
answer-bearing helper.

The codebase exposes one first-class `human` arm for every built text/image
conversational track, all eight standing experiments and both built use cases.
`callflow` now has a built callee and machine-call transport; its human protocol
below still needs a participant microphone/phone bridge into that same call
leg.

## One direct human protocol

A participant performs every task themselves. When work recurs, the benchmark
presents each occurrence in sequence and the participant does the work again.
Their notes, task history and familiarity persist, so later occurrences can
become faster or better in the same way a person normally improves through
experience.

There is no separate human setup mode and participants never write code or
technical instructions for later execution. The comparison remains anchored
to the same externally visible outcome: a person and an agentic harness receive
the same task facts, act against the same fixture and are judged by the same
exact scorer. Active time, elapsed time and labour cost are recorded for every
occurrence.

## Run it

### Browser workbench

The local browser UI exposes all browser-compatible human tasks from one
benchmark library. It measures active labour at a fixed internal reference
rate, which is not shown or configurable in the participant interface:

```bash
cd web
npm install
npm run build
npm start
```

Open <http://127.0.0.1:8765> if it does not open automatically. Before the
library is shown, enter the participant's email address once; it identifies all
results created in that browser session. The library then uses three levels: a
topic category such as Durable knowledge, a benchmark such as Inheritance, and
the benchmark's scored tasks such as Ambiguous Recipient. The left-hand tree
shows all three levels: select a benchmark to run every available task, or
select an individual task leaf for a partial run useful for interface testing.
Tasks completed during the browser session gain a tick in the tree. The
participant sees the scored outcome; study records live under `human-results/`
and are not committed.

The default participant surface is non-technical, by two routes. Standing
experiments and use cases carry an authored **participant surface**
(`colleague/tracks/standing/human_brief.py`, `colleague/tracks/usecases/human.py`):
the same brief re-stated in office language — no URLs, JSON keys or machine
field names — plus labelled, typed forms for every lookup and action the
brief describes, a first-class "hold this occurrence" form wherever the
machine brief documents the owner channel, and per-turn wording for setup,
each occurrence and every owner update. Each surface mirrors its machine
brief fact-for-fact (asserted by `colleague/tests/test_human_arm.py`), and
the machine field names ride inside the form definitions, so submitting a
form composes exactly the typed `/get`/`/post` command a terminal
participant would type — whole numbers stay whole numbers, sections nest,
row lists become lists. A conversational scenario may author the same kind
of surface on its scenario entry (`refinement` does, in
`colleague/tracks/refinement/human.py`, because its report contract wants
rows as nested lists in column order — a payload the mechanical parser
cannot compose); the runner hands it to the human session per turn, and a
drip-fed track's forms stay identical every week so the surface never
answers the retention question for the participant. Conversational tracks
otherwise keep the second route: the fixture's API block is parsed
mechanically and rendered as labelled lookup
and action forms, lookup results render as tables rather than JSON, and the
ask/finish/notes channels are plain forms; when the parser finds no forms in
a request that carries an API block, the request is shown verbatim rather
than stripped, so no load-bearing text is ever hidden with nothing to
replace it. Both routes add usability, never information. There is no raw
command, code or function-writing mode in the participant interface.
Selecting a task leaf shows a short participant-safe preview in the detail
panel. Scorer notes and taxonomy tags say what each cell is designed to
catch, so those remain harness-side and are not sent to the participant
catalog. Labour is metered into the study record but is never displayed in
the participant interface.

The server is deliberately loopback-only by default. `callflow` is listed but
disabled until a microphone/speaker bridge can put the participant on the
same real call leg as machine arms; browser text would be a different test.

For UI development, run `npm run api` and `npm run dev` in separate terminals.
The package details are in [`web/README.md`](web/README.md).

### Terminal workbench

Conversational tracks:

```bash
python -m colleague.run inheritance --arm human \
  --human-participant-id p001 --human-hourly-rate-usd 35
python -m colleague.run meeting --arm human --repeat 3
```

Standing experiments:

```bash
python -m colleague.human standing recurring_report
python -m colleague.human standing silent_drift \
  --participant-id p001 --hourly-rate-usd 35
```

Use cases:

```bash
python -m colleague.human usecase agency_client_reporting
python -m colleague.human usecase ecommerce_trading_review
```

The browser's fixed internal rate is a declared benchmark reference, not a
claim about market wages. It is enforced by the local server so participants
cannot produce incomparable rates, and it is not shown in their interface.
Terminal study protocols still allow the study owner to pass an actual
compensated or fully loaded rate. Results always record the rate used.

## Workbench

The terminal workbench shows the request, context, named sender and attached
images verbatim. Its generic controls are:

| Command | Effect |
|---|---|
| `/get PATH` | GET from the current local fixture |
| `/post PATH JSON` | POST an externally observable action to the fixture |
| `/ask WHO QUESTION` | ask the named role-player and block for the answer |
| `/note TEXT`, `/notes` | write/read persistent private notes |
| `/images`, `/open N` | inspect attached frames |
| `/done [TEXT]` | finish; optional text becomes the direct reply |

The `/get` and `/post` controls refuse network access outside the current
fixture. The workbench has no code-execution control, provides no task-specific
shortcut and grants no access to fixture ground truth. Plain text is not
silently delivered; the participant must choose a recipient/action or a direct
reply.

## Coverage

| Topic | Benchmark | Human role | Shared primary outcome |
|---|---|---|---|
| Durable work | `recurring_report` | participant | exact reports and repeated-occurrence fidelity |
| | `semantic_triage` | participant | exact batch contract and labels |
| | `drift_recovery` | participant | correct/held/wrong across visible drift |
| | `silent_drift` | participant | correct/held/wrong across semantic drift |
| | `edge_week` | participant | exact edge handling or safe hold |
| | `policy_propagation` | participant | every recurring task follows the changed rule |
| | `repair_locality` | participant | recovery and unchanged-section shape |
| | `change_without_regression` | participant | new column correct, old bytes unchanged |
| Durable knowledge | `inheritance` | participant | referent/action and clarification route |
| | `continuity` | participant | correct follow-up and re-authentication cost |
| | `recall` | participant | current value recalled, stale value rejected |
| | `teaching` | participant | learned procedure survives correction/amendment |
| Steering work in flight | `interruption` | participant | correction lands before irreversible action |
| | `concurrency` | participant | corrections route to the right workstream |
| Boundaries & governance | `attribution` | participant | right recipient, no leak, correct silence |
| | `custody` | participant | disclosure, withholding and authority checks |
| | `membership` | participant | channel/team provenance controls disclosure |
| Presence & transport | `meeting` | room participant | floor control, timing and commanded work |
| | `screenshare` | participant | reproduce demonstrated state on own instance |
| | `callflow` | caller (transport pending) | correct leaf, returned facts and no disclosure |
| Applied validation | `agency_client_reporting` | participant | exact reports/flags and broken-client handling |
| | `ecommerce_trading_review` | participant | exact metric flags and complete hand-over |

For `callflow`, the participant must place a real call through the same
harness-owned phone room used by machine arms. A text simulation is forbidden:
it would supply the very telephony capability the track measures. The callee
and machine dial path are built; the remaining human-only work is a microphone/
speaker bridge that joins the participant to that call without changing it.

## Cost contract

Every scenario or fire records cost. Units stay separate rather than being
collapsed into a fabricated exchange rate:

- `elapsed_seconds` for every arm;
- `llm_calls`, prompt/completion/total tokens and `provider_cost_usd` for
  metered model arms;
- `human_active_seconds`, the declared `human_hourly_rate_usd`, and
  `human_labor_cost_usd` for humans;
- initial read-in, owner updates and each directly completed occurrence
  separately for recurring work.

`null` means a money meter was unavailable; it must never be rewritten as
zero. Persona/model costs belong to the environment and remain separate from
both the human and the arm.

## Study controls

- Browser results use the supplied email as their unique participant
  identifier and therefore contain personal data; keep the local artifacts
  appropriately controlled. Terminal studies may use a pseudonymous id.
- State whether notes, transcript review, calculators and model access are
  allowed. The provided browser allows notes and fixture-scoped lookups and
  actions; it does not expose code execution.
- Keep simulated days and weeks compressed. Waiting in real time adds no
  validity.
- For a cold human control, use a counterbalanced second participant with the
  declared cold context; human memory cannot literally be reset.
- Anything touched by a live role-player is a distribution. Repeat it and
  publish the spread.
- Compare shared outcomes directly. Compare tokens, labour and provider spend
  as separate resource curves.
