# Reading this arm's fires table — and why there are three of them

This experiment was run **three times** for the OpenCode arm, because its
setup turned out to be the only bimodal behaviour in the suite. All three
runs are kept:

| run | what setup persisted | fire mode | correct | tokens/fire |
|---|---|---|---|---|
| `17-55-38Z` | nothing | wake_prompt | 0/8 | 38.8k (all wasted) |
| `17-58-45Z` (this one) | agent + runner script + cron spec | cron_spec | **8/8, 100%** | **8.8k** |
| `18-01-55Z` | agent + custom command + cron spec | cron_spec | **8/8, 100%** | 18.9k |

**Two of three setups produced a working automation.** The failure mode is
specific, and was read from the run's CLI log at the time (that log is no
longer committed — it captures resolved provider config and so can carry a
plaintext API key): in `17-55-38Z` the agent went
looking for a launchd job, hit OpenCode's own `external_directory`
permission auto-rejection on `~/Library/LaunchAgents`, and abandoned the
task without writing anything. The two successful runs instead wrote a
crontab spec into the workspace, which the firing rule executes.

**Conditional on setup succeeding, this is the second-cheapest arm in the
suite per firing** — 8.8k and 18.9k tokens against hermes's ~21.5k and
openclaw's ~30k, at the same 100% accuracy all four arms achieve on these
96 inquiries. Unify's distilled function is still an order of magnitude
below it at ~645.

The reason it is cheap is worth recording, because it is good design: the
agent authored a **custom agent definition** (`.opencode/agent/support-
triage.md`) and pointed its schedule at that, so each firing loads a
narrow purpose-built prompt rather than the full default agent context.
That is the same instinct as distilling a function — shrink what the model
has to read on every repeat — applied one level up, to the agent rather
than the code.

Setup cost is correspondingly higher than the other OpenCode experiments
(115k / 125k against 83k for the weekly report), because building the
agent, runner and schedule is more work than writing one script.
