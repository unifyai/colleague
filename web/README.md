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
fixture. Builder shell commands execute participant-authored code in the
run-local workspace, so a study must still declare and enforce its policy for
code, tools and network access.

`callflow` remains visible but disabled: replacing its audio call with browser
text would invalidate what the benchmark tests. It will become runnable when
the human microphone/speaker bridge is implemented.
