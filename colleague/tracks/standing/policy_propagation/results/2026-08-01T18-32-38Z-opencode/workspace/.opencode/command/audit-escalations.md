---
description: Audit escalation volume for one inquiry batch from the local support API.
agent: escalation-audit
---

Run exactly one escalation-audit batch now.

1. Execute exactly `curl -sS --fail http://127.0.0.1:8132/audits/last` and read the integer `last_seq` from its JSON response.
2. Execute exactly `curl -sS --fail 'http://127.0.0.1:8132/inquiries?after=N'`, replacing `N` with that integer.
3. If the returned inquiry list is empty, stop without making a POST request.
4. Otherwise, classify every returned inquiry from its `text`. An inquiry is urgent when it involves a charge, billing amount, or refund of $250 or more, or when the customer says they are blocked from working. Every other inquiry is normal. Do not infer that someone is blocked merely because they report a bug.
5. Build one JSON object with exactly these keys:
   - `batch_start_seq`: the smallest fetched `seq`, as an integer.
   - `batch_end_seq`: the largest fetched `seq`, as an integer.
   - `urgent_count`: the number of urgent inquiries, as an integer.
   - `total_count`: the number of fetched inquiries, as an integer.
   - `urgent_fraction`: `urgent_count / total_count`, rounded to two decimal places, as a JSON number.
6. Submit that object by executing exactly `curl -sS --fail -X POST -H 'Content-Type: application/json' --data-raw 'JSON' http://127.0.0.1:8132/audits`, replacing `JSON` with the compact JSON object. Make no other POST request.

Do not use shell pipelines, command substitution, temporary files, filesystem tools, or any commands other than the exact `curl` forms above. Do not process another batch during this run.
