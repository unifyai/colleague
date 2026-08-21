# Colleague Human Bench UI

A local React client for running Colleague's human arm in a browser. The
browser is only the participant surface: Python still creates each fixture,
records externally visible actions, applies the exact benchmark scorer and
writes the result artifact.

## Quick start

From this directory:

```bash
npm install
npm run build
npm start
```

`npm start` serves the production build at <http://127.0.0.1:8765> and opens
it in the default browser. It requires Python 3.12+ and the repository itself,
but no model or provider key. Human results are written under
`human-results/` at the repository root and are ignored by git.

The entry screen asks for the participant's email address before exposing the
benchmark library and keeps it for the browser session as the unique result
identifier. The library then distinguishes topic categories, benchmarks and
their scored tasks in one left-hand tree. Selecting a benchmark runs it in full;
selecting a task leaf reserves the detail panel for that task alone. Completed
tasks are ticked for the remainder of the participant's browser session.
Browser runs use a server-enforced internal reference rate; the client neither
shows it nor offers a rate control. Because result files contain the supplied
email, treat them as personal data even though they remain local by default.

For UI development, run the API and Vite in separate terminals:

```bash
npm run api
npm run dev
```

Then open <http://127.0.0.1:5173>. Vite proxies `/api` to the local Python
host on port 8765.

## Local safety boundary

The server binds only to loopback by default and state-changing requests use
a per-process token. Fixture GET/POST actions remain restricted to the active
fixture. The participant UI has no code or shell execution surface: recurring
work is presented again for the person to complete directly on each occurrence.

Standing experiments and use cases arrive with an authored participant
surface on each turn event — an office-language brief plus typed form
definitions, built in Python beside the fixture (see
`colleague/tracks/standing/human_brief.py`). `src/surface.tsx` renders it;
submissions compose the same `/get`/`/post` commands as the terminal, with
values typed the way the task contract expects (integers, nested sections,
row lists, booleans). Conversational tracks still derive their forms from the
request's API block in `src/contract.ts`; if nothing parses, the request is
shown verbatim instead of stripped.

`callflow` remains visible but disabled: replacing its audio call with browser
text would invalidate what the benchmark tests. It will become runnable when
the human microphone/speaker bridge is implemented.
