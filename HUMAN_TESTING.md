# Human testing

Every Colleague benchmark has a human-solvable primary outcome. Humans and
agent harnesses receive the same facts and are scored against the same
deterministic ground truth. The interface may be human-native — a workbench,
an image viewer or a call — but it must not add information or an
answer-bearing helper.

The codebase exposes a first-class `human` arm for every built text/image
conversational track, two human protocols for all eight standing experiments,
and the same two protocols for both built use cases. `callflow` now has a built
callee and machine-call transport; its human protocol below still needs a
participant microphone/phone bridge into that same call leg.

## Two human baselines

**Operator** is the direct, ARC-like baseline. A participant performs each
task or simulated wake themselves. It measures human correctness, active
labour, elapsed time and labour cost.

**Builder** preserves the architectural question in recurring work. A
participant creates an artifact once in a persistent workspace and supplies
the command fired on every wake. The artifact then runs unattended. The
participant returns only for owner messages and explicit operator-fix points.
Setup/update labour and unattended runtime are recorded separately.

Neither replaces the other. An operator baseline answers how much work a
person does; a builder baseline answers what a person can automate.

## Run it

### Browser workbench

The local browser UI exposes all browser-compatible human protocols from one
benchmark library and measures the declared labour rate throughout the run:

```bash
cd web
npm install
npm run build
npm start
```

Open <http://127.0.0.1:8765> if it does not open automatically. Choose a
benchmark, an available scenario or full track, operator/builder mode where
applicable, a pseudonymous participant id and the participant's compensated
or loaded hourly rate. Result JSON is available when scoring finishes. Local
results live under `human-results/` and are not committed.

The default participant surface is non-technical: the fixture's API block is
parsed mechanically and rendered as labelled lookup and action forms, lookup
results render as tables rather than JSON, and the ask/finish/notes channels
are plain forms. The forms compose exactly the `/get`, `/post`, `/ask`,
`/note` and `/done` commands a terminal participant would type, and they are
derived only from the request text every arm receives — usability is added,
information is not. A "Technical view" toggle restores the raw command
surface (and is the default in builder mode). Scenario picker cards show
titles only: per-scenario notes and taxonomy tags say what each cell
measures, which a participant must not read before running it. Labour is
metered exactly as before but is not displayed while the run is live; the
recorded figure appears with the result.

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
python -m colleague.human standing recurring_report --mode operator
python -m colleague.human standing silent_drift --mode builder \
  --participant-id p001 --hourly-rate-usd 35
```

Use cases:

```bash
python -m colleague.human usecase agency_client_reporting --mode operator
python -m colleague.human usecase ecommerce_trading_review --mode builder
```

The default `$30/hour` is a declared benchmark reference rate, not a claim
about market wages. A study should pass the participant's actual compensated
or fully loaded rate. Results always record the rate used.

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
| `/shell COMMAND` | work in the run-local persistent builder workspace |
| `/done [TEXT]` | finish; optional text becomes the direct reply |

The `/get` and `/post` controls refuse network access outside the current
fixture. Builder-mode shell commands are ordinary participant-authored code,
so the study protocol must enforce its declared network/tool policy just as it
does for a human using an editor. The workbench provides no task-specific
command and no access to fixture ground truth. Plain text is not silently
delivered; the participant must choose a recipient/action or a direct reply.

## Coverage

| Topic | Benchmark | Human role | Shared primary outcome |
|---|---|---|---|
| Durable work | `recurring_report` | operator + builder | exact reports and schedule/wake fidelity |
| | `semantic_triage` | operator + builder | exact batch contract and labels |
| | `drift_recovery` | operator + builder | correct/held/wrong across visible drift |
| | `silent_drift` | operator + builder | correct/held/wrong across semantic drift |
| | `edge_week` | operator + builder | exact edge handling or safe hold |
| | `policy_propagation` | operator + builder | every automation follows the changed rule |
| | `repair_locality` | operator + builder | recovery and unchanged-section shape |
| | `change_without_regression` | operator + builder | new column correct, old bytes unchanged |
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
| Applied validation | `agency_client_reporting` | operator + builder | exact reports/flags and broken-client handling |
| | `ecommerce_trading_review` | operator + builder | exact metric flags and complete hand-over |

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
- setup, owner update, operator repair and unattended fire phases separately
  for recurring work.

`null` means a money meter was unavailable; it must never be rewritten as
zero. Persona/model costs belong to the environment and remain separate from
both the human and the arm.

## Study controls

- Use a pseudonymous participant id; do not record names in result artifacts.
- State whether notes, transcript review, code, calculators and model access
  are allowed. The provided protocol allows notes and code; `/get` and `/post`
  are fixture-scoped, while access from participant-authored shell code must be
  controlled by the study environment.
- Keep simulated days and weeks compressed. Waiting in real time adds no
  validity.
- For a cold human control, use a counterbalanced second participant with the
  declared cold context; human memory cannot literally be reset.
- Anything touched by a live role-player is a distribution. Repeat it and
  publish the spread.
- Compare shared outcomes directly. Compare tokens, labour and provider spend
  as separate resource curves.
