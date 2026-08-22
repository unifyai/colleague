# Track: refinement

**Brief once, refine once, then ask for it again — and watch what froze.**

## The document-scale regime (2026-08-22)

This track is the first port of the suite-wide regime change recorded in
`SCENARIO_CHANGES.md` under 2026-08-22: no task remains at toy scale, and
there is no fixture API. Daniel shares each week's work as attachments —
a multi-page card statement, five vendor invoices, a stack of
scan-distorted receipts (30–50 pages a week; week 1 adds a twelve-section
onboarding brief PDF with the dormant conversion rule buried in section 9,
and the corporate rate sheet as a workbook) — and expects one normalised
`.xlsx` back on the same channel. The statement carries every charge and
no descriptions; invoice lines carry descriptions except for
receipt-backed charges, whose lines point at a receipt rendered as an
image-only scan. So the flag judgment requires reconciling three document
kinds, and for every judgment-bearing row it requires vision — text
extraction returns nothing for exactly the descriptions the flag checks
score, which `selftest` proves, along with byte-identical corpus
regeneration from the seed. The scorer parses the returned workbook
(title cell, header row, data rows in statement order) against ground
truth recomputed from the same seeded tables the renderers draw from,
under a declared tolerance policy — title case/whitespace folded, flags
as booleans or the words TRUE/FALSE, amounts exact text — that the
selftest sweeps to prove no verdict depends on a threshold. Scale dials
(`REFINEMENT_ROWS_PER_WEEK`, `REFINEMENT_RECEIPT_FRACTION`,
`REFINEMENT_DISTORT_FRACTION`) are the axes the crossover measurement
sweeps. Everything below this section that describes `/expenses`,
`/rates` or `POST /report` describes the retired API regime; the weeks,
the traps, the personas, the sleep chain and the DEGRADED/INVALID
semantics are unchanged and read as written. Deliverable return is
per-surface: the CM sends the file on its own channel (bridged to the
fixture's witness route); workspace arms name a path in their reply, or
their newest produced file is collected — how the file was found is
recorded in the run. **Verdicts across this boundary are a different
regime: every run below predates document scale and is labelled, not
deleted; none is comparable with document-scale runs.**

One recurring deliverable — a weekly client spend report — receives its spec
the way specs actually arrive: a prose brief, format feedback on the first
draft, then nothing restated for four weeks, then a one-sentence amendment.
The brief carries one dormant rule (foreign-currency rows convert at the
rates endpoint) that nothing exercises until week 5, and one standing
judgment (flag anything that looks like personal spending) whose wording the
fixture eventually turns hostile to shortcuts.

| Scenario | |
|---|---|
| `week_1_briefed` | The brief, dormant rule included. No format is fixed yet, so only filing is scored; the feedback that fixes the format is the next scenario. |
| `week_2_columns` | The feedback on the first draft: title exactly "Northwind Client Spend - Week 2", columns exactly `vendor, category, amount_eur, flagged` in order, amounts as euro strings with two decimals, rows as lists in API order. In force from this round on. |
| `week_3_replay` | "File the spend report for week 3" — nothing restated. The drip-fed spec is the procedure now. |
| `week_4_paraphrase` | The personal-spend items stop sharing any token with the earlier weeks' samples ("personal", "gift"), and a business item picks one of those tokens up. A keyword ladder distilled from the observed samples fails in both directions; the judgment the brief asked for does not. |
| `week_5_offcycle` | The first foreign-currency rows. A procedure frozen from the observed weeks — where every row was EUR — silently mis-converts; the brief's rule was sufficient all along. |
| `week_6_amendment` | One column renamed in one sentence (`amount_eur` → `amount`). The flags, the conversion, the order and the title are not mentioned and must not move — week 6's rows replay both traps, so the amendment week is a regression test for every earlier rule at once. |
| `unbriefed_control` | No brief, ever, in a session that never saw one. Establishes what the API alone yields. |

## The weeks sleep between requests

Requests that arrive weeks apart never find a warm process — the CM
retires its pod after ten idle minutes, gateways exit, laptops close.
Weeks 2–6 therefore declare `sleep`: between weeks the runner kills the
arm's process and boots a fresh one over the same durable world. The disk
survives (the CM's context tree, hermes's SQLite session rows, OpenClaw's
state dir, prime-agent's session files — each resumed through the
product's own reopen-yesterday's-chat path); process memory does not. An
arm that leaned on a warm in-context trajectory instead of its durable
stores loses exactly what it would lose in production.

## What the trap weeks measure

The suite already measured drip-fed retention (`teaching`) and exact
structural regression on a recurring artifact
(`standing/change_without_regression`) — separately. This track joins them
on one artifact and adds the question neither asks: **did the arm calibrate
where the structure ends and the judgment begins?**

An arm that automates this task well freezes the skeleton — fetch, iterate,
format, file — and keeps two joints fluid: the personal-spend call, and the
handling of inputs the observed weeks never showed. The two trap weeks are
aimed one at each failure:

- **Week 4** catches the *semantic downgrade*: a flag rule distilled into
  keywords from weeks 1–3 misses "Weekend spa stay with the family" and
  false-flags "Client gift baskets — holiday campaign". The labels are
  fixed by construction in the fixture's template tables, so the flag set
  is exact ground truth without a judge.
- **Week 5** catches *premature freezing*: the conversion rule was stated
  in the brief and then dormant for four weeks. An arm that distilled its
  procedure from observed behaviour rather than stated rules drops the
  branch it never saw run, and processes the USD rows as if they were
  normal — the silent failure mode. USD amounts are even by construction,
  so "nearest cent" at the fixture's 0.92 rate is never ambiguous.

Read together with the ledger, the outcomes separate the quadrants: cheap
and correct on the trap weeks is calibrated automation; cheap and wrong is
a procedure frozen too early; expensive and correct is an arm still paying
for planning it could have distilled; expensive and wrong is just bad.

## Asking is priced, not forbidden

Daniel answers questions as a persona — every answer he gives is one the
brief or the feedback already contained. A correct week that needed a
clarification resolves `DEGRADED` rather than `PASS` (`inheritance` set the
precedent: asking is not wrong, it is just expensive). That gives the
week-5 verdicts three legible rungs: remembered (PASS), noticed and asked
(DEGRADED — the surprise signal worked, the memory did not), silently wrong
(FAIL).

Daniel listens on every channel, for the whole track. A question asked in
the arm's *reply* — the failure mode that lost CI run 32556444813, where a
cold-booted arm asked for the week-2 source in its reply and the channel
was write-only — now gets his answer back as an ordinary inbound message
(the runner's conversation loop; sends the arm's product delivers to him
are witnessed on the fixture's `/reply`). The DEGRADED trigger keys off his
reply **labels**: any exchange labelled `restated`, whichever channel
carried it, prices the week. His memory accumulates his own sent messages,
so at week 6 the rename stands over the brief's original column name; his
trap discipline never confirms a flag decision or does conversion
arithmetic (the leak guard voids the cell — `INVALID` — if his stand-in
ever emits a computed conversion). The `unbriefed_control` meets a
scenario-scoped stand-in who has no format to give and is leak-guarded
against inventing one, so asking him is not a side door to the spec the
control proves undiscoverable.

Cost per week is reported from the ledger and never scored. Across the six
weeks that ledger is the measurement this track exists to produce: the
amortisation curve of a task whose spec was drip-fed — what each round
cost, and whether the rounds after the spec stabilised got cheap.

The control is what makes the later weeks readable. The exact format is not
discoverable from the API, so `unbriefed_control` resolves `UNSUPPORTED`
for everybody; an arm that passes it has told you its later weeks were
inference, not retention.

```bash
python -m colleague.run refinement --arm unify-cm
```

## First person-shaped run (2026-08-21, unify-cm, local — pre-duplex, pre-document-scale)

*Pre-duplex: this run predates the persona engine — Daniel answered only
through the clarification hook, and a question asked on any other channel
died unanswered. Its verdicts are not comparable with runs after the
duplex change and are kept labelled, not deleted. Pre-document-scale: it
also predates the 2026-08-22 regime — five API rows per week, no
documents, no attachments — so its verdicts and its amortisation curve
are non-comparable with document-scale runs on both axes.*

Run `2026-08-21T21-18-56Z-unify-cm-ca088c`, unify staging `34c62f2c2`
(verification master switch off by default), gpt-5.6-sol: **6/6 scoreable
cells pass**, `unbriefed_control` UNSUPPORTED as designed. The amortisation
curve is the finding: prompt tokens per week ran 534k → 796k → 1.09M →
1.60M → 1.79M → 1.66M (8.1M total, 210 calls; the provider-USD column is
null, not zero — 34 calls carried no provider price, and the void-cost
rule refuses to sum a partial column) — correctness converged and cost did
not. The conversational path does not yet bring stored
work back into later weeks — each round re-derives the procedure with the
previous trajectory in context — and whenever reuse lands in the product,
this curve is where it will show. (Earlier same-day runs through since-
retired arm surfaces showed the same rising shape; they predate the
person-shaped regime and the sleeping weeks, were never committed, and
are quoted nowhere per the no-figure-without-a-committed-summary rule.)

Run `python -m colleague.run refinement --arm human`. The same participant
receives the brief, the feedback and the amendment; notes persist, and the
unbriefed control gets a fresh workspace. Every week records active labour
and cost beside the exact structural score — the human curve is the
baseline the drip-fed amortisation claim is measured against.

## First duplex run (2026-08-22, unify-cm, local — pre-document-scale)

*Pre-document-scale: this run predates the same-day document-scale
regime — its weeks were five API rows against the retired fixture
endpoints. Its duplex findings stand; its verdicts and costs are not
comparable with document-scale runs.*

Run `2026-08-22T09-21-55Z-unify-cm-3adc33`, the first with the persona
engine live (colleague `94ec8be`, unify staging `004eb7f9d`, personas
gpt-5.6-sol direct): weeks 1–2 pass, weeks 3–6 fail on format retention
across the sleeps (wrong title, an invented seven-column schema — the
same shape the pre-duplex baseline showed on the same staging build),
control UNSUPPORTED as designed. The duplex evidence is the point of the
run. Ten persona exchanges, all on the reply channel, zero through the
hook: Daniel read every filed-report status and stayed silent on seven of
them; in week 4 he caught the wrong title from the arm's own report and
re-supplied the exact one (label `restated`, priced — the week still
failed on columns, so no credit moved); and week 6 replayed the motivating
incident and closed it — the arm announced "I couldn't locate the Week 6
finance file… nothing was changed", Daniel answered "Use the API details I
already gave you" (label `repointed`, nothing re-supplied), and the
resumed arm filed. Under the write-only reply channel that week was a
zero-filing dead end; under the duplex it is an answered conversation,
with the ping-pong visible in the ledger (week 6: 116 calls, 3.2M arm
tokens). Persona spend for the whole run: 13,626 tokens across 10
exchanges, in `persona_ledger.jsonl`, never in an arm column. No leak
guard hits; no INVALID cells. Arm totals: 27.5 min scenario wall, 250
calls, 7.0M tokens, $2.06 provider (week 6 unpriced calls void that
week's column under the void-cost rule).

In the browser workbench each week carries a participant surface
(`human.py`), because the report contract — a whole-number week, a column
list, rows as lists in column order with string amounts and boolean flags —
is a payload the workbench's generic form parser cannot compose. The
surface adds mechanics without adding memory: the forms are byte-identical
every week, the office-language request is a verbatim slice of the machine
utterance, and nothing pinned states the title, the machine column names,
the amount format or the flag rule — those stay in Daniel's messages, where
keeping hold of them is the thing being measured. The row cells are
labelled with what the expenses lookup itself shows; the participant still
types the week, the title and the column names, makes the flag call per
row, and does their own conversion in the amount cell — so every scored
check remains theirs. The unbriefed control shares the surface: it gains
the row shape a terminal participant would improvise and keeps measuring
what it exists to measure, since the exact title and column names are typed
or not at all. `test_refinement_surface_adds_mechanics_without_adding_memory`
pins all of this.

*(The participant-surface paragraph above describes the retired API
regime's forms. Under the document-scale regime the surface is file
mechanics — the week's documents download from the turn, and the
deliverable is a workbook the participant builds with their own tools:
in the terminal, saved under the session workspace and named in `/done`;
in the browser, upload is not built yet, so browser runs are read-only
previews. The same parity test now pins the file-shaped surface.)*

## First document-scale live run (2026-08-22, unify-cm, local — week 1 smoke)

Run `2026-08-22T15-40-59Z-unify-cm-ebedc7`, colleague 973390d (the regime
commit), unify checkout 004eb7f9d (staging branch; predates origin/staging's
Comms-persistence fix 52c34e857, acceptable for a single-week smoke that
crosses no sleep), gpt-5.6-sol, personas live: **week_1_briefed PASS** —
1021.6s wall, 98 arm calls, 7.55M tokens (7.49M prompt / 63k completion),
$3.81 provider; persona spend 1,012 tokens across 1 exchange, in its own
ledger. All 28 shared documents ingested through the CM's own attachment
machinery (`Attachments/aNNN_*` in the run-scoped file root); the returned
workbook (29,844 bytes) was witnessed on `/deliver` via
`unify-cm-channel` — the product's outbound attachment on its own send,
bridged by the egress tap.

Three findings, in the order they happened:

1. **The work was real and the arm did it.** It probed pypdf/pytesseract
   (absent), found PyMuPDF, rasterised the 20 image-only receipt scans and
   read them by vision, reconciled all 40 statement rows against invoice
   lines and receipts to the cent, extracted the FX table from the attached
   workbook, flagged 4 rows as personal (readable only from the scans), and
   self-validated a seven-tab draft before sending. Week 1 fixes no format,
   so only the returned file is scored; the format weeks are 2–6.

2. **Document scale flipped the distillation economics on week 1.** The
   storage reviewer — which declined to store a function sixteen times
   across the five-row regime's tied run — chose to distil here:
   `build_northwind_weekly_spend_workbook` (structured reconciliation +
   fx rates in, validated workbook out) is stored, with data acquisition
   deliberately kept outside it. This is the regime change doing exactly
   what it was built to do, on the first live week.

3. **One adapter gap, found and closed.** The product's outbound
   attachment path uploads to the adapters gateway (`/unify/attachment`,
   production contract); the embedded boot stood no gateway up, so the
   first two sends failed and the arm told Daniel so, honestly, both
   times. It then diagnosed the missing service from inside its sandbox —
   port-probed the default, read product and harness source, stood up its
   own gateway, repointed its settings in-process, and delivered on the
   third attempt ("the upload gateway issue has been repaired; the file is
   unchanged and checksum-verified"). The adapter now boots a loopback
   attachment gateway (`_AttachmentGatewayStub`, the self-host case the
   product's own comment names), so later runs exercise the send path
   without demanding self-repair first. Two boundary notes from the same
   episode: an embedded local run's sandbox can read the harness's own
   source (inherent to local runs — the CLI arms share the host too), and
   the arm's workaround wrote one stray file into the operator's real
   `~/Unity/Local/Attachments/` (`Northwind_Week_1_Client_Spend_Report_
   Draft.xlsx`), which is exactly the pollution the adapter's run-scoped
   file root exists to prevent — the root held for everything the product
   itself did; the stray came from the arm hand-picking the global path
   during its repair.

Cost context, reported never scored: the pre-document-scale week 1 ran
~534k prompt tokens; this week 1 ran 7.49M — with an unmeasured share
spent on the gateway self-repair loop, so the clean per-week figure waits
on the next run. Weeks 2–6 and the control have not run live under this
regime yet.
