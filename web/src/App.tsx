import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRun, getRun, initialize, runFileUrl, sendAction } from "./api";
import type { Benchmark, Catalog, RunEvent, RunSnapshot } from "./types";
import {
  BodyField,
  Endpoint,
  collectSuggestions,
  describeCommand,
  parseApiDoc,
  parseRoster,
  suggestionsFor,
} from "./contract";

type TechnicalTab = "request" | "ask" | "notes" | "builder" | "finish" | "console";

const money = new Intl.NumberFormat("en-GB", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

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
        <span>Colleague</span>
        <span className="edition">Human bench</span>
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
        `${item.title} ${item.description} ${item.family}`.toLowerCase().includes(query),
      ),
    }))
    .filter((family) => family.benchmarks.length);

  return (
    <main className="setup-layout">
      <section className="library-panel">
        <div className="section-kicker">Choose the work</div>
        <h1>How well does a person<br />handle the same job?</h1>
        <p className="lede">Same facts. Same fixture. Same exact scorer. Your time stays visible beside the outcome.</p>
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
            <div className="detail-heading">
              <div>
                <span className="eyebrow">{props.selected.family} / {kindLabel(props.selected.kind)}</span>
                <h2>{props.selected.title}</h2>
                <p>{props.selected.description}</p>
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
                  {/* Scenario notes and tags are study-designer metadata: they
                      say what each cell measures, which a participant must not
                      read before running it. Titles only. */}
                  <label className={`choice-card ${props.scenario === "" ? "active" : ""}`}>
                    <input type="radio" name="scenario" checked={props.scenario === ""} onChange={() => props.onScenario("")} />
                    <span><strong>Whole track</strong><small>Run each browser-compatible task in sequence — the standard protocol</small></span>
                  </label>
                  {props.selected.scenarios.map((item) => (
                    <label className={`choice-card compact ${props.scenario === item.id ? "active" : ""} ${!item.available ? "disabled" : ""}`} key={item.id}>
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
                        {!item.available && <small>{item.limitation}</small>}
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
                  <p className="field-note">Use a pseudonym and the participant’s compensated or fully loaded rate. Time is measured quietly in the background.</p>
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

/** The API block is rendered as forms, so the prose brief hides its lines. */
function stripApiBlock(request: string): string {
  return request
    .split("\n")
    .filter((line) => !/^\s*(GET|POST)\s+\S+/.test(line) && !/API at http/.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Harness chrome that duplicates the brief panel or narrates the terminal. */
function isHarnessChrome(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return true;
  return (
    /^=+$/.test(trimmed) ||
    trimmed.startsWith("SCENARIO:") ||
    trimmed.startsWith("FROM:") ||
    trimmed.startsWith("CONTEXT") ||
    trimmed.startsWith("REQUEST") ||
    trimmed.startsWith("IMAGES") ||
    trimmed.startsWith("Human workbench ready.") ||
    trimmed.startsWith("Enter actions; finish with") ||
    trimmed.startsWith("Commands:") ||
    /^\[[\w/]+\] scenario /.test(trimmed)
  );
}

function RunWorkspace({ run, events, benchmark, onError }: { run: RunSnapshot; events: RunEvent[]; benchmark: Benchmark | null; onError: (value: string) => void }) {
  const builder = run.request.mode === "builder";
  const [technical, setTechnical] = useState(builder);
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const turn = [...events].reverse().find((event) => event.type === "turn");
  const finalCost = [...events].reverse().find((event) => event.type === "cost")?.cost;
  const labour = Number(finalCost?.active_seconds || 0) * Number(run.request.hourlyRateUsd) / 3600;

  const endpoints = useMemo(() => parseApiDoc(turn?.request || ""), [turn?.request]);
  const roster = useMemo(() => parseRoster(`${turn?.context || ""}\n${turn?.request || ""}`), [turn?.context, turn?.request]);
  const pool = useMemo(
    () => collectSuggestions(events.filter((e) => e.type === "output" && e.text).map((e) => e.text as string)),
    [events],
  );

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
  const disabled = !run.awaitingInput || sending || complete;
  const briefRequest = technical ? turn?.request || "" : stripApiBlock(turn?.request || "");

  return (
    <main className="run-page">
      <section className="run-ribbon">
        <div>
          <span className={`run-dot ${run.status}`} />
          <strong>{benchmark?.title || run.request.benchmark}</strong>
          <span>{turn?.scenario ? turn.scenario.replaceAll("_", " ") : "Preparing first task"}</span>
        </div>
        <label className="view-toggle">
          <input type="checkbox" checked={technical} onChange={(event) => setTechnical(event.target.checked)} />
          <span>Technical view</span>
        </label>
      </section>

      {complete && <Completion run={run} labour={labour} />}

      <div className="run-grid">
        <section className="brief-panel">
          <div className="panel-label">Your brief</div>
          {turn ? (
            <>
              {turn.sender && <div className="sender-chip">From {turn.sender}</div>}
              {turn.context && <TextBlock label="What has been said" text={turn.context} />}
              {briefRequest && <TextBlock label="What you are asked to do" text={briefRequest} prominent />}
              {!!turn.images?.length && (
                <div className="image-list">
                  <h3>Attached frames</h3>
                  {turn.images.map((path, index) => (
                    <a key={path} href={runFileUrl(run.id, path)} target="_blank" rel="noreferrer">Frame {index + 1}<span>open ↗</span></a>
                  ))}
                </div>
              )}
            </>
          ) : <p className="empty-copy">Your first task will appear here in a moment.</p>}
          <div className="integrity-note"><span>◎</span><p><strong>Same rules for everyone</strong>These controls only carry out what you decide. Only recorded actions count.</p></div>
        </section>

        <section className="activity-panel">
          <div className="panel-heading"><span className="panel-label">What has happened</span>{technical && <span>{events.length} events</span>}</div>
          <div className="activity-feed" ref={feedRef} aria-live="polite">
            {events.filter((event) => displayEvent(event, technical)).slice(-120).map((event) => (
              <EventItem event={event} technical={technical} key={event.seq} />
            ))}
            {!events.length && <div className="empty-feed"><span>·</span><p>Getting ready…</p></div>}
          </div>
        </section>

        <section className="workbench-panel">
          <div className="panel-heading">
            <span className="panel-label">Your move</span>
            <span className={`input-state ${run.awaitingInput ? "ready" : "busy"}`}>{run.awaitingInput ? "Ready for you" : complete ? "Finished" : "Working…"}</span>
          </div>
          {technical ? (
            <TechnicalBench builder={builder} disabled={disabled} onSubmit={submit} />
          ) : (
            <FriendlyBench endpoints={endpoints} roster={roster} pool={pool} disabled={disabled} onSubmit={submit} />
          )}
        </section>
      </div>
    </main>
  );
}

function TextBlock({ label, text, prominent = false }: { label: string; text: string; prominent?: boolean }) {
  return <div className={`text-block ${prominent ? "prominent" : ""}`}><h3>{label}</h3><pre>{text}</pre></div>;
}

function displayEvent(event: RunEvent, technical: boolean) {
  if (event.type === "output" && !event.text?.trim()) return false;
  if (!technical && ["output", "log", "status"].includes(event.type) && isHarnessChrome(event.text || "")) return false;
  return ["turn", "correction", "output", "action", "log", "status", "error", "input_required"].includes(event.type);
}

/** A lookup/action result: render JSON as a table or list, never as code. */
function ResultView({ text }: { text: string }) {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return <pre>{text}</pre>;
  }
  return <JsonValue value={value} />;
}

function JsonValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <p className="quiet">Nothing there.</p>;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <p>{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <p className="quiet">Nothing there.</p>;
    if (value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
      const columns = [...new Set(value.flatMap((item) => Object.keys(item as object)))];
      return (
        <div className="result-table-wrap">
          <table className="result-table">
            <thead><tr>{columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>
              {value.map((item, index) => (
                <tr key={index}>{columns.map((c) => <td key={c}><JsonCell value={(item as Record<string, unknown>)[c]} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <ul className="result-list">{value.map((item, index) => <li key={index}><JsonValue value={item} /></li>)}</ul>;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return <p className="quiet">Nothing there.</p>;
  return (
    <dl className="result-object">
      {entries.map(([key, item]) => (
        <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd><JsonCell value={item} /></dd></div>
      ))}
    </dl>
  );
}

function JsonCell({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="quiet">—</span>;
  if (typeof value === "object") return <JsonValue value={value} />;
  return <span>{String(value)}</span>;
}

function EventItem({ event, technical }: { event: RunEvent; technical: boolean }) {
  const time = new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (event.type === "turn") {
    return <article className="event-item turn-event"><div className="event-glyph">↳</div><div><header><strong>New task</strong><time>{time}</time></header><p>{event.scenario?.replaceAll("_", " ")}</p></div></article>;
  }
  if (event.type === "correction") {
    return <article className="event-item correction-event"><div className="event-glyph">!</div><div><header><strong>{event.sender ? `${event.sender} interrupts` : "Interruption"}</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  }
  if (event.type === "action") {
    const label = technical ? undefined : describeCommand(event.command || "");
    return (
      <article className="event-item action-event">
        <div className="event-glyph">→</div>
        <div>
          <header><strong>{technical ? "Your action" : "You"}</strong><time>{time}</time></header>
          {technical ? <code>{event.command}</code> : <p>{label}</p>}
        </div>
      </article>
    );
  }
  if (event.type === "error") {
    return <article className="event-item error-event"><div className="event-glyph">×</div><div><header><strong>Run error</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  }
  if (event.type === "input_required") {
    return <article className="event-item input_required-event"><div className="event-glyph">·</div><div><header><strong>Ready</strong><time>{time}</time></header><p>{technical ? "Workbench ready for your next action." : "Your turn."}</p></div></article>;
  }
  const text = event.text || event.status || "Run updated";
  return (
    <article className={`event-item ${event.type}-event`}>
      <div className="event-glyph">·</div>
      <div>
        <header><strong>{event.type === "status" ? "Status" : technical ? "Harness" : "Result"}</strong><time>{time}</time></header>
        {technical ? <pre>{text}</pre> : <ResultView text={text} />}
      </div>
    </article>
  );
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
      <div className="completion-cost"><span>Recorded labour</span><strong>{money.format(labour)}</strong></div>
      {run.resultPath && <a className="result-link" href={runFileUrl(run.id, run.resultPath)} target="_blank" rel="noreferrer">Open result JSON ↗</a>}
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * Friendly workbench: the same commands, composed from labelled forms that
 * are derived mechanically from the request text every arm receives.
 * ------------------------------------------------------------------------- */

type Pool = ReturnType<typeof collectSuggestions>;

function FriendlyBench({ endpoints, roster, pool, disabled, onSubmit }: {
  endpoints: Endpoint[];
  roster: { id: string; label: string }[];
  pool: Pool;
  disabled: boolean;
  onSubmit: (command: string) => Promise<void>;
}) {
  const lookups = endpoints.filter((e) => e.method === "GET");
  const actions = endpoints.filter((e) => e.method === "POST");
  return (
    <div className="friendly-bench">
      {lookups.length > 0 && (
        <section className="bench-section">
          <h3>Look things up</h3>
          <p className="bench-hint">See the information in the workspace before you act.</p>
          {lookups.map((endpoint) => <LookupCard key={endpoint.method + endpoint.path} endpoint={endpoint} disabled={disabled} onSubmit={onSubmit} />)}
        </section>
      )}
      {actions.length > 0 && (
        <section className="bench-section">
          <h3>Take an action</h3>
          <p className="bench-hint">These are the things you can actually do. Actions count — look before you leap.</p>
          {actions.map((endpoint) => <ActionCard key={endpoint.method + endpoint.path} endpoint={endpoint} pool={pool} disabled={disabled} onSubmit={onSubmit} />)}
        </section>
      )}
      <section className="bench-section">
        <h3>Ask someone</h3>
        <p className="bench-hint">Not sure what was meant? Ask the person who would know, and wait for their answer.</p>
        <AskCard roster={roster} disabled={disabled} onSubmit={onSubmit} />
      </section>
      <section className="bench-section">
        <h3>Notepad</h3>
        <NotesCard disabled={disabled} onSubmit={onSubmit} />
      </section>
      <section className="bench-section finish-section">
        <h3>Finish this task</h3>
        <FinishCard disabled={disabled} onSubmit={onSubmit} />
      </section>
    </div>
  );
}

function LookupCard({ endpoint, disabled, onSubmit }: { endpoint: Endpoint; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const params = [...endpoint.pathParams, ...endpoint.queryParams];
  const missing = params.some((p) => !p.optional && !(values[p.name] || "").trim());

  function buildPath(): string {
    let path = endpoint.path;
    for (const param of endpoint.pathParams) {
      path = path.replace(`<${param.name}>`, encodeURIComponent((values[param.name] || "").trim()));
    }
    const query = endpoint.queryParams
      .filter((p) => (values[p.name] || "").trim())
      .map((p) => `${p.name}=${encodeURIComponent(values[p.name].trim())}`)
      .join("&");
    return query ? `${path}?${query}` : path;
  }

  return (
    <form
      className="bench-card"
      onSubmit={(event) => { event.preventDefault(); onSubmit(`/get ${buildPath()}`); }}
    >
      <div className="bench-card-row">
        <div className="bench-card-title">
          <strong>{endpoint.label}</strong>
          {endpoint.note && <small>{endpoint.note}</small>}
        </div>
        {params.map((param) => (
          <label className="inline-field" key={param.name}>
            <span>{param.name.replace(/_/g, " ")}</span>
            <input
              value={values[param.name] || ""}
              onChange={(event) => setValues((v) => ({ ...v, [param.name]: event.target.value }))}
              placeholder={param.hint}
            />
          </label>
        ))}
        <button className="bench-go" disabled={disabled || missing}>Look</button>
      </div>
    </form>
  );
}

function ActionCard({ endpoint, pool, disabled, onSubmit }: { endpoint: Endpoint; pool: Pool; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [pathValues, setPathValues] = useState<Record<string, string>>({});
  const missing =
    endpoint.fields.some((f) => !f.optional && !(values[f.key] || "").trim()) ||
    endpoint.pathParams.some((p) => !p.optional && !(pathValues[p.name] || "").trim());

  function buildCommand(): string {
    let path = endpoint.path;
    for (const param of endpoint.pathParams) {
      path = path.replace(`<${param.name}>`, encodeURIComponent((pathValues[param.name] || "").trim()));
    }
    const body: Record<string, unknown> = {};
    for (const field of endpoint.fields) {
      const raw = (values[field.key] || "").trim();
      if (!raw && field.optional) continue;
      body[field.key] = field.kind === "list" ? raw.split(",").map((s) => s.trim()).filter(Boolean) : raw;
    }
    return `/post ${path} ${JSON.stringify(body)}`;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSubmit(buildCommand());
    setOpen(false);
    setValues({});
  }

  if (!open) {
    return (
      <button className="bench-card bench-card-closed" type="button" disabled={disabled} onClick={() => setOpen(true)}>
        <strong>{endpoint.label}</strong>
        {endpoint.note && <small>{endpoint.note}</small>}
        <span className="open-marker">＋</span>
      </button>
    );
  }

  return (
    <form className="bench-card bench-card-open" onSubmit={submit}>
      <div className="bench-card-title"><strong>{endpoint.label}</strong>{endpoint.note && <small>{endpoint.note}</small>}</div>
      {endpoint.pathParams.map((param) => (
        <label className="stacked-field" key={param.name}>
          <span>{param.name.replace(/_/g, " ")}</span>
          <input value={pathValues[param.name] || ""} onChange={(event) => setPathValues((v) => ({ ...v, [param.name]: event.target.value }))} placeholder={param.hint} />
        </label>
      ))}
      {endpoint.fields.map((field) => (
        <FieldInput key={field.key} field={field} value={values[field.key] || ""} pool={pool} onChange={(next) => setValues((v) => ({ ...v, [field.key]: next }))} />
      ))}
      <div className="bench-card-actions">
        <button type="button" className="quiet-button" onClick={() => setOpen(false)}>Cancel</button>
        <button className="bench-go" disabled={disabled || missing}>{endpoint.label}</button>
      </div>
    </form>
  );
}

function FieldInput({ field, value, pool, onChange }: { field: BodyField; value: string; pool: Pool; onChange: (value: string) => void }) {
  const label = field.label + (field.optional ? " (optional)" : "");
  if (field.options) {
    return (
      <label className="stacked-field">
        <span>{label}</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Choose…</option>
          {field.options.map((option) => <option key={option} value={option}>{option.replace(/_/g, " ")}</option>)}
        </select>
      </label>
    );
  }
  if (field.kind === "date") {
    return (
      <label className="stacked-field">
        <span>{label}</span>
        <input type="date" value={value} onChange={(event) => onChange(event.target.value)} />
      </label>
    );
  }
  const suggestions = suggestionsFor(field, pool);
  const listId = suggestions.length ? `dl-${field.key}` : undefined;
  if (field.kind === "long") {
    return (
      <label className="stacked-field">
        <span>{label}</span>
        <textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)} placeholder={field.hint} />
      </label>
    );
  }
  return (
    <label className="stacked-field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={field.hint} list={listId} />
      {listId && (
        <datalist id={listId}>
          {suggestions.map((s) => <option key={s} value={s} />)}
        </datalist>
      )}
    </label>
  );
}

function AskCard({ roster, disabled, onSubmit }: { roster: { id: string; label: string }[]; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [who, setWho] = useState("");
  const [other, setOther] = useState("");
  const [question, setQuestion] = useState("");
  const target = who === "__other__" ? other.trim().toLowerCase() : who;
  return (
    <form
      className="bench-card bench-card-open"
      onSubmit={(event) => { event.preventDefault(); onSubmit(`/ask ${target} ${question.trim()}`); setQuestion(""); }}
    >
      <label className="stacked-field">
        <span>Who</span>
        <select value={who} onChange={(event) => setWho(event.target.value)}>
          <option value="">Choose a person…</option>
          {roster.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
          <option value="__other__">Someone else…</option>
        </select>
      </label>
      {who === "__other__" && (
        <label className="stacked-field"><span>Their first name</span><input value={other} onChange={(event) => setOther(event.target.value)} /></label>
      )}
      <label className="stacked-field">
        <span>Your question</span>
        <textarea rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Which Sarah did you mean?" />
      </label>
      <button className="bench-go" disabled={disabled || !target || !question.trim()}>Ask and wait for the answer</button>
    </form>
  );
}

function NotesCard({ disabled, onSubmit }: { disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  return (
    <form className="bench-card bench-card-open" onSubmit={(event) => { event.preventDefault(); onSubmit(`/note ${note.trim()}`); setNote(""); }}>
      <label className="stacked-field">
        <span>Write yourself a note (kept between tasks)</span>
        <textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="The deploy window moved to Wednesday 11:00" />
      </label>
      <div className="bench-card-actions">
        <button type="button" className="quiet-button" disabled={disabled} onClick={() => onSubmit("/notes")}>Show my notes</button>
        <button className="bench-go" disabled={disabled || !note.trim()}>Save note</button>
      </div>
    </form>
  );
}

function FinishCard({ disabled, onSubmit }: { disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [reply, setReply] = useState("");
  return (
    <form className="bench-card bench-card-open" onSubmit={(event) => { event.preventDefault(); onSubmit(`/done ${reply.trim()}`.trim()); setReply(""); }}>
      <label className="stacked-field">
        <span>Reply to send back (leave empty for none)</span>
        <textarea rows={3} value={reply} onChange={(event) => setReply(event.target.value)} placeholder="It’s done — the report went to Sarah Chen." />
      </label>
      <button className="bench-go finish-go" disabled={disabled}>I’m finished with this task</button>
    </form>
  );
}

/* ---------------------------------------------------------------------------
 * Technical workbench: the original tabbed surface, unchanged in behaviour.
 * ------------------------------------------------------------------------- */

function TechnicalBench({ builder, disabled, onSubmit }: { builder: boolean; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
  const [tab, setTab] = useState<TechnicalTab>("request");
  return (
    <>
      <nav className="action-tabs" aria-label="Workbench actions">
        {(["request", "ask", "notes", ...(builder ? ["builder"] : []), "finish", "console"] as TechnicalTab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>
        ))}
      </nav>
      <ActionPane kind={tab} disabled={disabled} onSubmit={onSubmit} />
      <div className="workbench-rule"><span>!</span><p>Plain text is never sent implicitly. Choose an action and a destination.</p></div>
    </>
  );
}

function ActionPane({ kind, disabled, onSubmit }: { kind: TechnicalTab; disabled: boolean; onSubmit: (command: string) => Promise<void> }) {
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
