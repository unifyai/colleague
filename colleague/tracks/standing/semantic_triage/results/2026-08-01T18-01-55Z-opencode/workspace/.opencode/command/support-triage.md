---
description: Triage one batch of new inquiries from the local support API.
agent: support-triage
---

Perform exactly one support-triage run:

1. GET `http://127.0.0.1:8128/batches/last` and read its integer `last_seq`.
2. GET `http://127.0.0.1:8128/inquiries?after=N`, replacing `N` with that
   `last_seq`.
3. If the returned inquiry list is empty, stop without making a POST request.
4. Otherwise, understand what each customer needs and assign exactly one category:
   - `refund`: they want money back for something they were charged.
   - `bug`: something in the product is broken or not working correctly.
   - `sales`: they want to buy, upgrade, get a quote, or discuss pricing.
   - `other`: anything else.
5. Classification must be semantic, not keyword matching. Inquiries can express the
   same need in many different ways.
6. POST JSON to `http://127.0.0.1:8128/batches`. The top-level object must contain
   exactly `batch_start_seq`, `batch_end_seq`, and `classifications`.
   `batch_start_seq` is the smallest fetched sequence, `batch_end_seq` is the
   largest, and `classifications` contains exactly one object for every fetched
   inquiry, each shaped as `{"seq": int, "category": str}`. Include no unfetched
   sequence and omit no fetched sequence.

Do not ask for confirmation. Do not access any other endpoint.
