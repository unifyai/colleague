# Reading this arm's fires table

Same shape as the weekly-report arm: a prompt-driven isolated cron job
("Hourly customer inquiry triage", `payload.kind: agentTurn`), so every
fire boots an agent turn — there is no zero-token mode to reach for and,
unlike hermes, no attempt at one.

- **Accuracy tied at 100%** with both other arms across all 96 golden
  inquiries. Three different architectures, same model, no scorer
  daylight — this experiment's whole story stays cost.
- **Cheapest setup once again** (84k vs hermes 154k vs unify 1.46M
  including the distillation run), because the agent authored one precise
  cron payload and stopped.
- **Most expensive steady state of the three**: ~30k tokens / 4 calls /
  ~21 s per fire (hermes ~21.5k / 5 calls; unify ~645 / 1 focused
  `query_llm` call). The turn re-reads its system prompt, workspace
  bootstrap files, and the full inquiry batch every hour, forever.
- Break-even against unify's one-time distillation lands near fire 47
  (~2 days of hourly firing); against hermes it never catches up.
