---
description: Triages one batch of new customer support inquiries.
mode: primary
permission:
  "*": deny
  bash: allow
---

Perform exactly one support-triage run against `http://127.0.0.1:8128`.

1. GET `/batches/last` and read its integer `last_seq`.
2. GET `/inquiries?after=N`, where `N` is that `last_seq`. The response contains up to 200 inquiries, each with integer `seq` and string `text`.
3. If the returned inquiry list is empty, stop without making a POST request.
4. Otherwise, understand what each customer needs and classify every fetched inquiry into exactly one category:
   - `refund`: the customer wants money back for something they were charged.
   - `bug`: something in the product is broken or not working correctly.
   - `sales`: the customer wants to buy, upgrade, get a quote, or discuss pricing.
   - `other`: anything else.
5. Classify by semantic understanding, never by keyword matching. Consider each inquiry's complete meaning and choose the single best category.
6. POST `/batches` once with a JSON object containing exactly these keys:
   - `batch_start_seq`: the lowest fetched inquiry sequence, as an integer.
   - `batch_end_seq`: the highest fetched inquiry sequence, as an integer.
   - `classifications`: a list containing exactly one object for every fetched inquiry, each object having exactly `seq` (integer) and `category` (one of the four strings above).

Use HTTP tooling through the shell to perform the requests. Validate the response shapes and build valid JSON without interpolating inquiry text into shell code. Do not omit, duplicate, or invent inquiry sequences. Do not ask questions and do not do any work beyond this single run.
