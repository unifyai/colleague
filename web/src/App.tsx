import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRun, getRun, initialize, runFileUrl, sendAction } from "./api";
import type { Benchmark, Catalog, RunEvent, RunSnapshot } from "./types";

type ActionKind = "request" | "ask" | "notes" | "builder" | "finish" | "console";

const money = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function formatDuration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function kindLabel(kind: Benchmark["kind"]) {
  return kind === "conversational" ? "Conversation" : kind === "standing" ? "Recurring" : "Use case";
}

function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selectedId, setSelectedId] = useState("inheritance");
  const [search, setSearch] = useState("");
  const [scenario, setScenario] = useState("");
  const [mode, setMode] = useState("participant");
  const [participantId, setParticipantId] = useState("p001");
  const [hourlyRate, setHourlyRate] = useState(30);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    initialize().then(setCatalog).catch((cause) => setError(String(cause.message || cause)));
  }, []);

  const selected = useMemo(
    () => catalog?.benchmarks.find((item) => item.id === selectedId) || null,
    [catalog, selectedId],
  );

  useEffect(() => {
    if (!selected) return;
    setScenario("");
    setMode(selected.modes[0]);
  }, [selected]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getRun(run.id, run.lastSeq);
        if (cancelled) return;
        if (next.events.length) setEvents((current) => [...current, ...next.events]);
        setRun(next);
      } catch (cause) {
        if (!cancelled) setError(String((cause as Error).message || cause));
      }
    };
    const timer = window.setInterval(poll, 650);
    poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.id, run?.status, run?.lastSeq]);

  async function startRun() {
    if (!selected) return;
    setStarting(true);
    setError("");
    setEvents([]);
    try {
      const created = await createRun({
        kind: selected.kind,
        benchmark: selected.id,
        scenario: scenario || undefined,
        mode,
        participantId,
        hourlyRateUsd: hourlyRate,
      });
      setRun(created);
    } catch (cause) {
      setError(String((cause as Error).message || cause));
    } finally {
      setStarting(false);
    }
  }

  function reset() {
    setRun(null);
    setEvents([]);
    setError("");
  }

  if (!catalog) {
    return (
      <main className="boot-screen">
        <div className="brand-mark">C</div>
        <p>{error || "Preparing the human benchmark…"}</p>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <Header run={run} onExit={reset} />
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")} aria-label="Dismiss error">×</button>
        </div>
      )}
      {run ? (
        <RunWorkspace
          run={run}
          events={events}
          benchmark={catalog.benchmarks.find((item) => item.id === run.request.benchmark) || null}
          onError={setError}
        />
      ) : (
        <Setup
          catalog={catalog}
          selected={selected}
          selectedId={selectedId}
          search={search}
          scenario={scenario}
          mode={mode}
          participantId={participantId}
          hourlyRate={hourlyRate}
          starting={starting}
          onSearch={setSearch}
          onSelect={setSelectedId}
          onScenario={setScenario}
          onMode={setMode}
          onParticipant={setParticipantId}
          onRate={setHourlyRate}
          onStart={startRun}
        />
      )}
    </div>
  );
}

function Header({ run, onExit }: { run: RunSnapshot | null; onExit: () => void }) {
  return (
    <header className="topbar">
      <div className="wordmark">
        <span className="brand-mark small">C</span>
        <span>COLLEAGUE</span>
        <span className="edition">HUMAN BENCH</span>
      </div>
      <div className="topbar-meta">
        <span className="local-pill"><i /> local only</span>
        {run && <button className="text-button" onClick={onExit}>← Benchmark library</button>}
      </div>
    </header>
  );
}

type SetupProps = {
  catalog: Catalog;
  selected: Benchmark | null;
  selectedId: string;
  search: string;
  scenario: string;
  mode: string;
  participantId: string;
  hourlyRate: number;
  starting: boolean;
  onSearch: (value: string) => void;
  onSelect: (value: string) => void;
  onScenario: (value: string) => void;
  onMode: (value: string) => void;
  onParticipant: (value: string) => void;
  onRate: (value: number) => void;
  onStart: () => void;
};

function Setup(props: SetupProps) {
  const query = props.search.trim().toLowerCase();
  const families = props.catalog.families
    .map((family) => ({
      ...family,
      benchmarks: family.benchmarks.filter((item) =>
        `${item.title} ${item.description} ${item.family} ${item.tags ?? ""} ${item.scenarios
          .map((s) => `${s.title} ${s.tags}`)
          .join(" ")}`
          .toLowerCase()
          .includes(query),
      ),
    }))
    .filter((family) => family.benchmarks.length);

  return (
    <main className="setup-layout">
      <section className="library-panel">
        <div className="section-kicker">Choose the work</div>
        <h1>How well does a person<br />handle the same job?</h1>
        <p className="lede">Same facts. Same fixture. Same exact scorer. Your time and labour stay visible beside the outcome.</p>
        <label className="search-box">
          <span>⌕</span>
          <input value={props.search} onChange={(event) => props.onSearch(event.target.value)} placeholder="Find a benchmark" />
        </label>
        <div className="benchmark-list">
          {families.map((family) => (
            <div className="family-group" key={family.name}>
              <h2>{family.name}</h2>
              {family.benchmarks.map((item) => (
                <button
                  key={`${item.kind}-${item.id}`}
                  className={`benchmark-row ${props.selectedId === item.id ? "selected" : ""}`}
                  onClick={() => props.onSelect(item.id)}
                >
                  <span className="benchmark-index">{String(props.catalog.benchmarks.indexOf(item) + 1).padStart(2, "0")}</span>
                  <span className="benchmark-name">
                    <strong>{item.title}</strong>
                    <small>{kindLabel(item.kind)}</small>
                  </span>
                  {!item.available ? <span className="pending-tag">audio pending</span> : <span className="arrow">↗</span>}
                </button>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="setup-detail">
        {props.selected && (
          <>
            <div className="detail-number">{String(props.catalog.benchmarks.indexOf(props.selected) + 1).padStart(2, "0")}</div>
            <div className="detail-heading">
              <div>
                <span className="eyebrow">{props.selected.family} / {kindLabel(props.selected.kind)}</span>
                <h2>{props.selected.title}</h2>
                <p>{props.selected.description}</p>
                {props.selected.tags && <p className="scenario-tags">{props.selected.tags}</p>}
              </div>
              <span className={`availability ${props.selected.available ? "ready" : "pending"}`}>
                {props.selected.available ? "Ready locally" : "Not yet runnable"}
              </span>
            </div>

            {props.selected.limitation && <div className="limitation"><strong>Current boundary</strong>{props.selected.limitation}</div>}

            <div className="configuration-grid">
              {props.selected.scenarios.length > 0 && (
                <fieldset className="config-block scenario-block">
                  <legend>Run scope</legend>
                  <label className={`choice-card ${props.scenario === "" ? "active" : ""}`}>
                    <input type="radio" name="scenario" checked={props.scenario === ""} onChange={() => props.onScenario("")} />
                    <span><strong>Available track</strong><small>Run each browser-compatible scenario in sequence</small></span>
                  </label>
                  {props.selected.scenarios.map((item) => (
                    <label className={`choice-card ${props.scenario === item.id ? "active" : ""} ${!item.available ? "disabled" : ""}`} key={item.id}>
                      <input
                        type="radio"
                        name="scenario"
                        value={item.id}
                        disabled={!item.available}
                        checked={props.scenario === item.id}
                        onChange={() => props.onScenario(item.id)}
                      />
                      <span>
                        <strong>{item.title}</strong>
                        <small>{item.available ? item.description : item.limitation}</small>
                        {item.tags && <small className="scenario-tags">{item.tags}</small>}
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}

              <div className="config-column">
                {props.selected.modes.length > 1 && (
                  <fieldset className="config-block">
                    <legend>Human baseline</legend>
                    <div className="segmented">
                      {props.selected.modes.map((item) => (
                        <button key={item} className={props.mode === item ? "active" : ""} onClick={() => props.onMode(item)}>
                          {item}
                        </button>
                      ))}
                    </div>
                    <p className="field-note">
                      {props.mode === "builder"
                        ? "Build once; your frozen artifact fires unattended. Updates and repairs are separately timed."
                        : "Perform each task or compressed wake directly yourself."}
                    </p>
                  </fieldset>
                )}
                <fieldset className="config-block participant-fields">
                  <legend>Measurement</legend>
                  <label>
                    <span>Participant ID</span>
                    <input value={props.participantId} onChange={(event) => props.onParticipant(event.target.value)} maxLength={64} />
                  </label>
                  <label>
                    <span>Loaded rate <em>USD / hour</em></span>
                    <input type="number" min="0" step="1" value={props.hourlyRate} onChange={(event) => props.onRate(Number(event.target.value))} />
                  </label>
                  <p className="field-note">Use a pseudonym and the participant’s compensated or fully loaded rate.</p>
                </fieldset>
              </div>
            </div>

            <div className="start-strip">
              <div><strong>No model keys needed</strong><span>Results remain on this machine.</span></div>
              <button className="primary-button" disabled={!props.selected.available || props.starting || !props.participantId} onClick={props.onStart}>
                {props.starting ? "Preparing…" : "Begin benchmark"}<span>→</span>
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
}

function RunWorkspace({ run, events, benchmark, onError }: { run: RunSnapshot; events: RunEvent[]; benchmark: Benchmark | null; onError: (value: string) => void }) {
  const [tab, setTab] = useState<ActionKind>("request");
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const turn = [...events].reverse().find((event) => event.type === "turn");
  const finalCost = [...events].reverse().find((event) => event.type === "cost")?.cost;
  const measuredActiveSeconds = Number(finalCost?.active_seconds || 0);
  const activeSeconds = run.status === "running"
    ? Math.max(measuredActiveSeconds, run.elapsedSeconds)
    : measuredActiveSeconds || run.elapsedSeconds;
  const labour = activeSeconds * Number(run.request.hourlyRateUsd) / 3600;

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [events.length]);

  async function submit(command: string) {
    setSending(true);
    try {
      await sendAction(run.id, command);
    } catch (cause) {
      onError(String((cause as Error).message || cause));
    } finally {
      setSending(false);
    }
  }

  const complete = run.status === "complete" || run.status === "error";
  return (
    <main className="run-page">
      <section className="run-ribbon">
        <div>
          <span className={`run-dot ${run.status}`} />
          <strong>{benchmark?.title || run.request.benchmark}</strong>
          <span>{turn?.scenario ? turn.scenario.replaceAll("_", " ") : "Preparing first task"}</span>
        </div>
        <div className="live-metrics">
          <Metric label="Elapsed" value={formatDuration(run.elapsedSeconds)} />
          <Metric label="Labour estimate" value={money.format(labour)} />
          <Metric label="Rate" value={`${money.format(run.request.hourlyRateUsd)}/h`} />
        </div>
      </section>

      {complete && <Completion run={run} labour={labour} />}

      <div className="run-grid">
        <section className="brief-panel">
          <div className="panel-label">Current brief</div>
          {turn ? (
            <>
              {turn.sender && <div className="sender-chip">From {turn.sender}</div>}
              {turn.context && <TextBlock label="Context" text={turn.context} />}
              <TextBlock label="Request" text={turn.request || ""} prominent />
              {!!turn.images?.length && (
                <div className="image-list">
                  <h3>Attached frames</h3>
                  {turn.images.map((path, index) => (
                    <a key={path} href={runFileUrl(run.id, path)} target="_blank" rel="noreferrer">Frame {index + 1}<span>open ↗</span></a>
                  ))}
                </div>
              )}
            </>
          ) : <p className="empty-copy">The first task will appear here when its fixture is ready.</p>}
          <div className="integrity-note"><span>◎</span><p><strong>Same scorer</strong>The browser adds controls, not answers. Only fixture-observed actions count.</p></div>
        </section>

        <section className="activity-panel">
          <div className="panel-heading"><span className="panel-label">Run activity</span><span>{events.length} events</span></div>
          <div className="activity-feed" ref={feedRef} aria-live="polite">
            {events.filter(displayEvent).slice(-120).map((event) => <EventItem event={event} key={event.seq} />)}
            {!events.length && <div className="empty-feed"><span>·</span><p>Waiting for the fixture</p></div>}
          </div>
        </section>

        <section className="workbench-panel">
          <div className="panel-heading">
            <span className="panel-label">Workbench</span>
            <span className={`input-state ${run.awaitingInput ? "ready" : "busy"}`}>{run.awaitingInput ? "Your move" : complete ? "Closed" : "Processing"}</span>
          </div>
          <nav className="action-tabs" aria-label="Workbench actions">
            {(["request", "ask", "notes", ...(run.request.mode === "builder" ? ["builder"] : []), "finish", "console"] as ActionKind[]).map((item) => (
              <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>
            ))}
          </nav>
          <ActionPane kind={tab} disabled={!run.awaitingInput || sending || complete} onSubmit={submit} />
          <div className="workbench-rule"><span>!</span><p>Plain text is never sent implicitly. Choose an action and a destination.</p></div>
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function TextBlock({ label, text, prominent = false }: { label: string; text: string; prominent?: boolean }) {
  return <div className={`text-block ${prominent ? "prominent" : ""}`}><h3>{label}</h3><pre>{text}</pre></div>;
}

function displayEvent(event: RunEvent) {
  if (event.type === "output" && !event.text?.trim()) return false;
  return ["turn", "correction", "output", "action", "log", "status", "error", "input_required"].includes(event.type);
}

function EventItem({ event }: { event: RunEvent }) {
  const time = new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  if (event.type === "turn") return <article className="event-item turn-event"><div className="event-glyph">↳</div><div><header><strong>New task</strong><time>{time}</time></header><p>{event.scenario?.replaceAll("_", " ")}</p></div></article>;
  if (event.type === "correction") return <article className="event-item correction-event"><div className="event-glyph">!</div><div><header><strong>Correction · {event.sender || "participant"}</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  if (event.type === "action") return <article className="event-item action-event"><div className="event-glyph">→</div><div><header><strong>Your action</strong><time>{time}</time></header><code>{event.command}</code></div></article>;
  if (event.type === "error") return <article className="event-item error-event"><div className="event-glyph">×</div><div><header><strong>Run error</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  const text = event.text || (event.type === "input_required" ? "Workbench ready for your next action." : event.status || "Run updated");
  return <article className={`event-item ${event.type}-event`}><div className="event-glyph">·</div><div><header><strong>{event.type === "input_required" ? "Ready" : event.type === "status" ? "Status" : "Harness"}</strong><time>{time}</time></header><pre>{text}</pre></div></article>;
}

function Completion({ run, labour }: { run: RunSnapshot; labour: number }) {
  const measured = run.status === "complete";
  const credited = run.exitCode === 0;
  return (
    <section className={`completion ${run.status}`}>
      <div className="completion-mark">{measured ? (credited ? "✓" : "≈") : "×"}</div>
      <div>
        <span>{measured ? "Run measured" : "Run stopped"}</span>
        <h2>{measured ? (credited ? "All scored work was credited." : "The run completed with one or more misses.") : run.error || "The harness could not measure this run."}</h2>
      </div>
      <div className="completion-cost"><span>Estimated labour</span><strong>{money.format(labour)}</strong></div>
      {run.resultPath && <a className="result-link" href={runFileUrl(run.id, run.resultPath)} target="_blank" rel="noreferrer">Open result JSON ↗</a>}
    </section>
  );
}

function ActionPane({ kind, disabled, onSubmit }: { kind: ActionKind; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  if (kind === "request") return <RequestAction disabled={disabled} onSubmit={onSubmit} />;
  if (kind === "ask") return <TwoFieldAction title="Ask a participant" firstLabel="Who" firstPlaceholder="priya" secondLabel="Question" secondPlaceholder="Which Sarah did you mean?" button="Ask and wait" build={(a, b) => `/ask ${a} ${b}`} disabled={disabled} onSubmit={onSubmit} />;
  if (kind === "notes") return <SingleAction title="Persistent private note" label="Note" placeholder="The portal manager is Leeds" button="Save note" build={(value) => `/note ${value}`} disabled={disabled} onSubmit={onSubmit} secondary={{ label: "Show saved notes", command: "/notes" }} />;
  if (kind === "builder") return <SingleAction title="Builder workspace" label="Shell command" placeholder="python report.py" button="Run in workspace" build={(value) => `/shell ${value}`} disabled={disabled} onSubmit={onSubmit} warning="Participant-authored code runs locally. Follow your study’s declared tool and network policy." />;
  if (kind === "finish") return <SingleAction title="Finish this task" label="Optional direct reply" placeholder="Done — I sent the report to Priya." button="Finish turn" build={(value) => `/done ${value}`.trim()} disabled={disabled} onSubmit={onSubmit} secondary={{ label: "Finish without a reply", command: "/done" }} />;
  return <SingleAction title="Raw workbench command" label="Command" placeholder="/get /notes" button="Send command" build={(value) => value} disabled={disabled} onSubmit={onSubmit} />;
}

function RequestAction({ disabled, onSubmit }: { disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [method, setMethod] = useState<"GET" | "POST">("GET");
  const [path, setPath] = useState("/");
  const [body, setBody] = useState("{\n  \n}");
  const [problem, setProblem] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setProblem("");
    if (!path.trim()) return setProblem("Enter a fixture path.");
    if (method === "POST") {
      try { JSON.parse(body); } catch { return setProblem("The POST body must be valid JSON."); }
    }
    await onSubmit(method === "GET" ? `/get ${path.trim()}` : `/post ${path.trim()} ${body.trim()}`);
  }
  return (
    <form className="action-form" onSubmit={submit}>
      <h3>Fixture request</h3>
      <div className="method-switch"><button type="button" className={method === "GET" ? "active" : ""} onClick={() => setMethod("GET")}>GET</button><button type="button" className={method === "POST" ? "active" : ""} onClick={() => setMethod("POST")}>POST</button></div>
      <label><span>Path</span><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/inbox" /></label>
      {method === "POST" && <label><span>JSON body</span><textarea value={body} onChange={(event) => setBody(event.target.value)} rows={8} spellCheck={false} /></label>}
      {problem && <p className="form-problem">{problem}</p>}
      <button className="action-submit" disabled={disabled}>{disabled ? "Wait for your move" : `Send ${method}`}<span>→</span></button>
    </form>
  );
}

function SingleAction({ title, label, placeholder, button, build, disabled, onSubmit, warning, secondary }: { title: string; label: string; placeholder: string; button: string; build: (value: string) => string; disabled: boolean; onSubmit: (command: string) => Promise<void>; warning?: string; secondary?: { label: string; command: string } }) {
  const [value, setValue] = useState("");
  return (
    <form className="action-form" onSubmit={(event) => { event.preventDefault(); onSubmit(build(value)); setValue(""); }}>
      <h3>{title}</h3>
      <label><span>{label}</span><textarea rows={5} value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} /></label>
      {warning && <p className="form-warning">{warning}</p>}
      <button className="action-submit" disabled={disabled || !value.trim()}>{disabled ? "Wait for your move" : button}<span>→</span></button>
      {secondary && <button className="secondary-action" type="button" disabled={disabled} onClick={() => onSubmit(secondary.command)}>{secondary.label}</button>}
    </form>
  );
}

function TwoFieldAction({ title, firstLabel, firstPlaceholder, secondLabel, secondPlaceholder, button, build, disabled, onSubmit }: { title: string; firstLabel: string; firstPlaceholder: string; secondLabel: string; secondPlaceholder: string; button: string; build: (a: string, b: string) => string; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  return (
    <form className="action-form" onSubmit={(event) => { event.preventDefault(); onSubmit(build(first, second)); setSecond(""); }}>
      <h3>{title}</h3>
      <label><span>{firstLabel}</span><input value={first} onChange={(event) => setFirst(event.target.value)} placeholder={firstPlaceholder} /></label>
      <label><span>{secondLabel}</span><textarea rows={5} value={second} onChange={(event) => setSecond(event.target.value)} placeholder={secondPlaceholder} /></label>
      <button className="action-submit" disabled={disabled || !first.trim() || !second.trim()}>{disabled ? "Wait for your move" : button}<span>→</span></button>
    </form>
  );
}

export default App;
