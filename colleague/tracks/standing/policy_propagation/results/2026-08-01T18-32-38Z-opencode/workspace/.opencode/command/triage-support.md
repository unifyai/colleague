---
description: Submit an urgent-inquiry digest for one batch from the local support API.
agent: support-triage
---

Run exactly one support-digest batch now.

1. Execute exactly `curl -sS --fail http://127.0.0.1:8132/digests/last` and read the integer `last_seq` from its JSON response.
2. Execute exactly `curl -sS --fail 'http://127.0.0.1:8132/inquiries?after=N'`, replacing `N` with that integer.
3. If the returned inquiry list is empty, stop without making a POST request.
4. Otherwise, determine whether every returned inquiry is urgent. An inquiry is urgent only when it involves a charge, billing amount, or refund of $250 or more, or when the customer says they are blocked from working. Every other inquiry is normal. Do not infer that someone is blocked merely because they report a bug.
5. Classify each urgent inquiry exactly once using its `text`:
   - `refund`: they want money back for a charge.
   - `bug`: something is broken or not working.
   - `sales`: they want to buy, upgrade, get a quote, or discuss pricing.
   - `other`: anything else.
6. Build one JSON object with exactly these top-level keys:
   - `batch_start_seq`: the smallest fetched `seq`, as an integer.
   - `batch_end_seq`: the largest fetched `seq`, as an integer.
   - `urgent_by_category`: an object with exactly the keys `refund`, `bug`, `sales`, and `other`, whose integer values count urgent inquiries in each category. Include all four keys even when a count is zero.
   - `urgent_total`: an integer equal to the sum of the four category counts.
7. Submit that object by executing exactly `curl -sS --fail -X POST -H 'Content-Type: application/json' --data-raw 'JSON' http://127.0.0.1:8132/digests`, replacing `JSON` with the compact JSON object. Make no other POST request.

Do not use shell pipelines, command substitution, temporary files, filesystem tools, or any commands other than the exact `curl` forms above. Do not process another batch during this run.
