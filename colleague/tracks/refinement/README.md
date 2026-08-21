# Track: refinement

**Brief once, refine once, then ask for it again — and watch what froze.**

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

## Human protocol

Run `python -m colleague.run refinement --arm human`. The same participant
receives the brief, the feedback and the amendment; notes persist, and the
unbriefed control gets a fresh workspace. Every week records active labour
and cost beside the exact structural score — the human curve is the
baseline the drip-fed amortisation claim is measured against.

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
