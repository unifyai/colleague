
## Post-run observation: the fix session daemonized

During the operator-fix session ("fix it so it resumes working
unattended"), the hermes agent did more than repair its script: it started
a gateway process and installed a persistent macOS LaunchAgent
(`ai.hermes.gateway.plist`) pointed at this throwaway HERMES_HOME, using a
separately installed hermes it found on the machine. That service kept
firing the benchmark job hourly after the run ended (each firing failed:
the fixture was down). The service and process were removed, the job
disabled (see jobs.json `paused_reason`), and both hermes drivers now
defuse cron jobs, gateway processes, and launch agents at finalize.
