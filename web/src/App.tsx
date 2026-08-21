import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRun, getRun, initialize, runFileUrl, sendAction } from "./api";
import type { Benchmark, Catalog, RunEvent, RunSnapshot, Surface } from "./types";
import {
  BodyField,
  Endpoint,
  collectSuggestions,
  describeCommand,
  parseApiDoc,
  parseRoster,
  suggestionsFor,
} from "./contract";
import { SurfaceBrief, SurfaceRequest, SurfaceSections } from "./surface";

const PARTICIPANT_EMAIL_KEY = "colleague-human-participant-email";
const COMPLETED_TASKS_KEY_PREFIX = "colleague-human-completed:";

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function savedParticipantEmail(): string {
  try {
    const value = window.sessionStorage.getItem(PARTICIPANT_EMAIL_KEY) || "";
    return isValidEmail(value) ? value : "";
  } catch {
    return "";
  }
}

function taskKey(benchmark: Benchmark, scenarioId?: string): string {
  return `${benchmark.kind}:${benchmark.id}:${scenarioId || "__benchmark__"}`;
}

function completedTasksKey(email: string): string {
  return `${COMPLETED_TASKS_KEY_PREFIX}${email}`;
}

function savedCompletedTasks(email: string): Set<string> {
  if (!email) return new Set();
  try {
    const value = JSON.parse(window.sessionStorage.getItem(completedTasksKey(email)) || "[]");
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

function kindLabel(kind: Benchmark["kind"]) {
  return kind === "conversational" ? "Conversation" : kind === "standing" ? "Recurring" : "Use case";
}

function experienceDescription(benchmark: Benchmark, singleTask: boolean): string {
  if (benchmark.kind === "standing") {
    return "Work progresses across several simulated periods. New requests and corrections may arrive, and your work needs to remain accurate as circumstances change.";
  }
  if (benchmark.kind === "usecase") {
    return "Complete a realistic end-to-end workplace workflow using the records and tools provided.";
  }
  if (singleTask) {
    return "Review the workplace context, investigate what you need and respond to the request with the available tools.";
  }
  return "Complete each workplace scenario in sequence. Every task has its own context, request and independently scored outcome.";
}

function contextDescription(benchmark: Benchmark): string {
  if (benchmark.kind === "standing") return "A workspace that changes over time";
  if (benchmark.kind === "usecase") return "Realistic workflow data and tools";
  return "Messages, people and workplace records";
}

function titleFromId(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function benchmarkTaskLabel(benchmark: Benchmark): string {
  const count = benchmark.scenarios.filter((scenario) => scenario.available).length;
  if (!benchmark.scenarios.length) return `1 task · ${kindLabel(benchmark.kind)}`;
  if (!count) return `${benchmark.scenarios.length} tasks · unavailable`;
  return `${count} ${count === 1 ? "task" : "tasks"} · ${kindLabel(benchmark.kind)}`;
}

function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selectedId, setSelectedId] = useState("inheritance");
  const [search, setSearch] = useState("");
  const [scenario, setScenario] = useState("ambiguous_recipient");
  const [participantEmail, setParticipantEmail] = useState(savedParticipantEmail);
  const [identityReady, setIdentityReady] = useState(() => Boolean(savedParticipantEmail()));
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [completedTasks, setCompletedTasks] = useState<Set<string>>(() =>
    savedCompletedTasks(savedParticipantEmail()),
  );
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    initialize()
      .then(({ catalog: nextCatalog }) => {
        setCatalog(nextCatalog);
      })
      .catch((cause) => setError(String(cause.message || cause)));
  }, []);

  const selected = useMemo(
    () => catalog?.benchmarks.find((item) => item.id === selectedId) || null,
    [catalog, selectedId],
  );

  useEffect(() => {
    if (!identityReady) {
      setCompletedTasks(new Set());
      return;
    }
    setCompletedTasks(savedCompletedTasks(participantEmail));
  }, [identityReady, participantEmail]);

  useEffect(() => {
    if (!catalog || run?.status !== "complete") return;
    const benchmark = catalog.benchmarks.find(
      (item) => item.kind === run.request.kind && item.id === run.request.benchmark,
    );
    if (!benchmark) return;

    const completed = run.request.scenario
      ? [taskKey(benchmark, run.request.scenario)]
      : benchmark.scenarios.filter((item) => item.available).map((item) => taskKey(benchmark, item.id));
    if (!completed.length) completed.push(taskKey(benchmark));

    setCompletedTasks((current) => {
      if (completed.every((key) => current.has(key))) return current;
      const next = new Set([...current, ...completed]);
      try {
        window.sessionStorage.setItem(completedTasksKey(participantEmail), JSON.stringify([...next]));
      } catch {
        // Completion marks still remain in React state for this page lifetime.
      }
      return next;
    });
  }, [catalog, participantEmail, run?.id, run?.status]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getRun(run.id, run.lastSeq);
        if (cancelled) return;
        if (next.events.length) setEvents((current) => [...current, ...next.events]);
        setRun(next);
        setError((current) => current.startsWith("Lost contact with the local runner") ? "" : current);
      } catch (cause) {
        if (!cancelled) {
          const message = String((cause as Error).message || cause);
          setError(
            message === "Failed to fetch"
              ? "Lost contact with the local runner — retrying automatically."
              : message,
          );
        }
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
    if (!selected || !identityReady) return;
    setStarting(true);
    setError("");
    setEvents([]);
    try {
      const created = await createRun({
        kind: selected.kind,
        benchmark: selected.id,
        scenario: scenario || undefined,
        participantEmail: participantEmail.trim().toLowerCase(),
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

  function confirmIdentity() {
    const normalized = participantEmail.trim().toLowerCase();
    if (!isValidEmail(normalized)) return;
    setParticipantEmail(normalized);
    setIdentityReady(true);
    try {
      window.sessionStorage.setItem(PARTICIPANT_EMAIL_KEY, normalized);
    } catch {
      // Storage can be unavailable in hardened browsers; React state still
      // keeps the identity for the current page lifetime.
    }
  }

  function changeIdentity() {
    setIdentityReady(false);
    try {
      window.sessionStorage.removeItem(PARTICIPANT_EMAIL_KEY);
    } catch {
      // See confirmIdentity: the gate still works without browser storage.
    }
  }

  function selectBenchmark(benchmark: Benchmark) {
    setSelectedId(benchmark.id);
    setScenario("");
  }

  function selectTask(benchmark: Benchmark, scenarioId: string) {
    setSelectedId(benchmark.id);
    setScenario(scenarioId);
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
      <Header
        run={run}
        participantEmail={identityReady ? participantEmail : ""}
        onExit={reset}
        onChangeParticipant={changeIdentity}
      />
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")} aria-label="Dismiss error">×</button>
        </div>
      )}
      {!identityReady ? (
        <IdentityGate
          participantEmail={participantEmail}
          onParticipantEmail={setParticipantEmail}
          onContinue={confirmIdentity}
        />
      ) : run ? (
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
          completedTasks={completedTasks}
          starting={starting}
          onSearch={setSearch}
          onSelectBenchmark={selectBenchmark}
          onSelectTask={selectTask}
          onStart={startRun}
        />
      )}
    </div>
  );
}

function Header({
  run,
  participantEmail,
  onExit,
  onChangeParticipant,
}: {
  run: RunSnapshot | null;
  participantEmail: string;
  onExit: () => void;
  onChangeParticipant: () => void;
}) {
  return (
    <header className="topbar">
      <div className="wordmark">
        <span className="brand-mark small">C</span>
        <span>Colleague</span>
        <span className="edition">Human benchmark</span>
      </div>
      <div className="topbar-meta">
        <span className="local-pill"><i /> results stay local</span>
        {participantEmail && !run && (
          <button className="participant-chip" onClick={onChangeParticipant} title="Change participant email">
            <span>{participantEmail}</span><small>Change</small>
          </button>
        )}
        {run && <button className="text-button" onClick={onExit}>← Benchmark library</button>}
      </div>
    </header>
  );
}

function IdentityGate({
  participantEmail,
  onParticipantEmail,
  onContinue,
}: {
  participantEmail: string;
  onParticipantEmail: (value: string) => void;
  onContinue: () => void;
}) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onContinue();
  }

  return (
    <main className="identity-page">
      <section className="identity-card" aria-labelledby="identity-title">
        <div className="identity-intro">
          <span className="section-kicker">Colleague human benchmark</span>
          <h1 id="identity-title">Handle the same workplace tasks as an AI colleague</h1>
          <p>Complete realistic tasks involving conversations, documents, decisions and follow-ups. Your work is evaluated against the same facts and outcomes used for AI systems.</p>
          <ul className="benchmark-overview-list">
            <li><span>1</span><div><strong>Choose a capability</strong><small>Benchmarks cover memory, coordination, governance and recurring work.</small></div></li>
            <li><span>2</span><div><strong>Work through the brief</strong><small>Review the context, use the available workplace tools and decide what to do.</small></div></li>
            <li><span>3</span><div><strong>Receive a scored result</strong><small>See whether the completed work met the benchmark.</small></div></li>
          </ul>
        </div>
        <form className="identity-form" onSubmit={submit}>
          <label>
            <span>Email address</span>
            <input
              autoFocus
              type="email"
              value={participantEmail}
              onChange={(event) => onParticipantEmail(event.target.value)}
              placeholder="you@company.com"
              autoComplete="email"
              maxLength={254}
              required
            />
          </label>
          <p className="identity-privacy">Results are saved locally and linked to this email.</p>
          <button className="primary-button" type="submit" disabled={!isValidEmail(participantEmail)}>
            View benchmarks <span>→</span>
          </button>
        </form>
      </section>
    </main>
  );
}

type SetupProps = {
  catalog: Catalog;
  selected: Benchmark | null;
  selectedId: string;
  search: string;
  scenario: string;
  completedTasks: Set<string>;
  starting: boolean;
  onSearch: (value: string) => void;
  onSelectBenchmark: (benchmark: Benchmark) => void;
  onSelectTask: (benchmark: Benchmark, scenarioId: string) => void;
  onStart: () => void;
};

function Setup(props: SetupProps) {
  const query = props.search.trim().toLowerCase();
  const availableTasks = props.selected?.scenarios.filter((item) => item.available) || [];
  const selectedTask = props.scenario
    ? props.selected?.scenarios.find((item) => item.id === props.scenario) || null
    : null;
  const selectedTaskIndex = selectedTask
    ? (props.selected?.scenarios.findIndex((item) => item.id === selectedTask.id) ?? -1) + 1
    : 0;
  const selectionAvailable = selectedTask ? selectedTask.available : Boolean(props.selected?.available);
  const hierarchyOrder = props.catalog.families.flatMap((family) => family.benchmarks);
  const families = props.catalog.families
    .map((family) => ({
      ...family,
      benchmarks: family.benchmarks.filter((item) =>
        `${item.title} ${item.description} ${item.family} ${item.scenarios.map((task) => `${task.title} ${task.description}`).join(" ")}`
          .toLowerCase()
          .includes(query),
      ),
    }))
    .filter((family) => family.benchmarks.length);

  function benchmarkProgress(benchmark: Benchmark): { completed: number; total: number } {
    const tasks = benchmark.scenarios.filter((item) => item.available);
    if (!tasks.length) {
      return { completed: props.completedTasks.has(taskKey(benchmark)) ? 1 : 0, total: 1 };
    }
    return {
      completed: tasks.filter((item) => props.completedTasks.has(taskKey(benchmark, item.id))).length,
      total: tasks.length,
    };
  }

  return (
    <main className="setup-layout">
      <section className="library-panel">
        <div className="section-kicker">Benchmarks</div>
        <h1>Choose a task</h1>
        <p className="lede">Benchmarks group tasks that measure the same workplace capability. Select one task, or select its benchmark to complete the full set.</p>
        <label className="search-box">
          <span>⌕</span>
          <input value={props.search} onChange={(event) => props.onSearch(event.target.value)} placeholder="Find a benchmark or task" />
        </label>
        <nav className="benchmark-list" aria-label="Benchmark and task tree">
          {families.map((family) => (
            <div className="family-group" key={family.name}>
              <h2><span>{family.name}</span><small>Category</small></h2>
              {family.benchmarks.map((item) => {
                const progress = benchmarkProgress(item);
                const benchmarkSelected = props.selectedId === item.id && !props.scenario;
                const benchmarkNumber = hierarchyOrder.findIndex(
                  (candidate) => candidate.kind === item.kind && candidate.id === item.id,
                ) + 1;
                return (
                  <div className="benchmark-tree-node" key={`${item.kind}-${item.id}`}>
                    <button
                      className={`benchmark-row ${benchmarkSelected ? "selected" : ""} ${props.selectedId === item.id ? "active-parent" : ""}`}
                      onClick={() => props.onSelectBenchmark(item)}
                      aria-current={benchmarkSelected ? "page" : undefined}
                    >
                      <span className="benchmark-index"><small>Benchmark</small><strong>{String(benchmarkNumber).padStart(2, "0")}</strong></span>
                      <span className="benchmark-name">
                        <strong>{item.title}</strong>
                        <small>{benchmarkTaskLabel(item)}</small>
                      </span>
                      {!item.available ? (
                        <span className="pending-tag">pending</span>
                      ) : progress.completed === progress.total ? (
                        <span className="tree-check" aria-label="Benchmark complete">✓</span>
                      ) : (
                        <span className="tree-progress" aria-label={`${progress.completed} of ${progress.total} tasks complete`}>
                          {progress.completed}/{progress.total}
                        </span>
                      )}
                    </button>
                    {item.scenarios.length > 0 && (
                      <div className="task-tree" role="group" aria-label={`${item.title} tasks`}>
                        {item.scenarios.map((task, index) => {
                          const taskSelected = props.selectedId === item.id && props.scenario === task.id;
                          const complete = props.completedTasks.has(taskKey(item, task.id));
                          return (
                            <button
                              className={`task-tree-row ${taskSelected ? "selected" : ""} ${!task.available ? "disabled" : ""}`}
                              key={task.id}
                              disabled={!task.available}
                              onClick={() => props.onSelectTask(item, task.id)}
                              aria-current={taskSelected ? "page" : undefined}
                            >
                              <span className="task-tree-index">Task {index + 1}</span>
                              <span>{task.title}</span>
                              {complete ? <span className="tree-check" aria-label="Task complete">✓</span> : <span className="task-tree-state" aria-hidden="true" />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </nav>
      </section>

      <section className="setup-detail">
        {props.selected && (
          <>
            <div className="detail-heading">
              <div>
                <span className="eyebrow">
                  {props.selected.family} category / {props.selected.title} benchmark
                  {selectedTask ? ` / Task ${selectedTaskIndex}` : ""}
                </span>
                <h2>{selectedTask ? selectedTask.title : availableTasks.length ? `Full ${props.selected.title} benchmark` : props.selected.title}</h2>
                <p>
                  {selectedTask
                    ? selectedTask.description
                    : availableTasks.length
                      ? `Complete all ${availableTasks.length} scored tasks in this benchmark, one after another.`
                      : props.selected.description}
                </p>
                <span className="benchmark-size">
                  {selectedTask
                    ? `Task ${selectedTaskIndex} of ${props.selected.scenarios.length}`
                    : availableTasks.length
                      ? `${availableTasks.length} scored tasks`
                      : `${kindLabel(props.selected.kind)} benchmark`}
                </span>
              </div>
              <span className={`availability ${selectionAvailable ? "ready" : "pending"}`}>
                {selectionAvailable ? "Available" : "Unavailable"}
              </span>
            </div>

            {(selectedTask?.limitation || props.selected.limitation) && (
              <div className="limitation">
                <strong>Why this is unavailable</strong>
                {selectedTask?.limitation || props.selected.limitation}
              </div>
            )}

            <section className="task-selection-detail" aria-labelledby="selection-detail-title">
              <div className="selection-kind">
                <span>Overview</span>
                {selectedTask && props.completedTasks.has(taskKey(props.selected, selectedTask.id)) && (
                  <strong><span className="tree-check" aria-hidden="true">✓</span> Completed this session</strong>
                )}
              </div>
              <h3 id="selection-detail-title">
                {selectedTask
                  ? "One workplace scenario"
                  : availableTasks.length
                    ? `${availableTasks.length} related workplace scenarios`
                    : "One complete workplace protocol"}
              </h3>
              <p>{experienceDescription(props.selected, Boolean(selectedTask))}</p>
              <div className="selection-facts">
                <div><span>Scope</span><strong>{selectedTask ? "1 independently scored task" : availableTasks.length ? `${availableTasks.length} tasks in sequence` : "1 end-to-end workflow"}</strong></div>
                <div><span>Context</span><strong>{contextDescription(props.selected)}</strong></div>
                <div><span>Measures</span><strong>Whether the completed work is correct</strong></div>
              </div>
            </section>

            <div className="start-strip">
              <div>
                <strong>{selectedTask ? selectedTask.title : availableTasks.length ? `Full ${props.selected.title} benchmark` : props.selected.title}</strong>
                <span>{selectedTask ? "1 scored task" : availableTasks.length ? `${availableTasks.length} scored tasks` : "1 scored workflow"}</span>
              </div>
              <button className="primary-button" disabled={!selectionAvailable || props.starting} onClick={props.onStart}>
                {props.starting ? "Preparing…" : selectedTask ? "Begin task" : availableTasks.length ? "Begin full benchmark" : "Begin benchmark"}<span>→</span>
              </button>
            </div>
          </>
        )}
      </section>
    </main>
  );
}

/** The API contract is rendered as forms, so the prose brief hides the
 * paragraphs that speak in URLs, endpoints and verbs. Everything else — the
 * actual ask, in office language — stays. If stripping would leave nothing,
 * the caller falls back to the verbatim request instead. */
function stripApiBlock(request: string): string {
  const paragraphs = request.split(/\n{2,}/).filter((part) => part.trim());
  const technical = (part: string) =>
    /https?:\/\//.test(part) ||
    /^\s*[-•]?\s*(GET|POST)\s+\S+/m.test(part) ||
    /\bendpoint\b/i.test(part) ||
    /\bPOST(ing|ed)?\b/.test(part);
  const kept = paragraphs.filter((part) => !technical(part));
  if (!kept.length) return request.trim();
  return kept.join("\n\n").trim();
}

type BriefPerson = { id: string; name: string; role: string; email: string };
type BriefMessage = { sender: BriefPerson; text: string };

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts.length === 1
    ? parts[0].slice(0, 2).toUpperCase()
    : `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

/** Parse the labelled plain-text transcript every arm receives. This is only
 * presentation: no facts are added and unmatched text falls back verbatim. */
function parseConversationContext(text: string): {
  people: BriefPerson[];
  messages: BriefMessage[];
  remainder: string;
} {
  const people: BriefPerson[] = [];
  const messages: BriefMessage[] = [];
  const remainder: string[] = [];
  let inConversation = false;

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^People in this workspace:$/i.test(line)) continue;
    if (/^Conversation so far:$/i.test(line)) {
      inConversation = true;
      continue;
    }

    if (!inConversation) {
      const person = /^-\s*(.+?)\s*\(([^)]+)\),\s*([^\s]+@[^\s]+?)(?=\.\s|$)/.exec(line);
      if (person) {
        people.push({
          id: person[3].split("@")[0].toLowerCase(),
          name: person[1].trim(),
          role: person[2].trim(),
          email: person[3].trim(),
        });
      } else {
        remainder.push(line);
      }
      continue;
    }

    const message = /^\[([^\]—]+?)\s*—\s*([^\]]+)\]\s*(.*)$/.exec(line);
    if (message) {
      const name = message[1].trim();
      const role = message[2].trim();
      const known = people.find((person) => person.name === name);
      messages.push({
        sender: known || {
          id: name.split(/\s+/)[0].toLowerCase(),
          name,
          role,
          email: "",
        },
        text: message[3].trim(),
      });
    } else if (messages.length) {
      messages[messages.length - 1].text += `\n${line}`;
    } else {
      remainder.push(line);
    }
  }

  return { people, messages, remainder: remainder.join("\n") };
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
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const turn = [...events].reverse().find((event) => event.type === "turn");
  const endpoints = useMemo(() => parseApiDoc(turn?.request || ""), [turn?.request]);
  const roster = useMemo(() => parseRoster(`${turn?.context || ""}\n${turn?.request || ""}`), [turn?.context, turn?.request]);
  const requester = roster.find((person) => person.id === turn?.sender)?.label || turn?.sender || "";
  const pool = useMemo(
    () => collectSuggestions(events.filter((e) => e.type === "output" && e.text).map((e) => e.text as string)),
    [events],
  );
  const surface = (turn?.surface as Surface | null | undefined) || null;
  const commandLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const lookup of surface?.lookups || []) labels[lookup.path] = lookup.label;
    for (const action of surface?.actions || []) labels[action.path] = action.label;
    if (surface?.hold) labels[surface.hold.path] = surface.hold.label;
    return labels;
  }, [surface]);

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
  // When the mechanical parse finds no forms in a request that clearly
  // carries an API block, stripping would hide load-bearing text with
  // nothing to replace it — show the request verbatim instead.
  const strippedRequest = stripApiBlock(turn?.request || "");
  const briefRequest =
    !endpoints.length && /https?:\/\//.test(turn?.request || "")
      ? (turn?.request || "").trim()
      : strippedRequest;

  return (
    <main className="run-page">
      <section className="run-ribbon">
        <div>
          <span className={`run-dot ${run.status}`} />
          <strong>{benchmark?.title || run.request.benchmark}</strong>
          <span>{turn?.scenario ? titleFromId(turn.scenario) : "Loading task"}</span>
        </div>
      </section>

      {complete && <Completion run={run} />}

      <div className="run-grid">
        <section className="brief-panel">
          <div className="panel-label">Task brief</div>
          {turn ? (
            <>
              {surface ? (
                <>
                  <SurfaceRequest surface={surface} />
                  <SurfaceBrief surface={surface} />
                </>
              ) : (
                <>
                  {turn.context && <ConversationBrief text={turn.context} />}
                  {briefRequest && <TaskBrief text={briefRequest} requester={requester} />}
                </>
              )}
              {!!turn.images?.length && (
                <div className="image-list">
                  <h3>Attachments</h3>
                  {turn.images.map((path, index) => (
                    <a key={path} href={runFileUrl(run.id, path)} target="_blank" rel="noreferrer">Frame {index + 1}<span>open ↗</span></a>
                  ))}
                </div>
              )}
            </>
          ) : <p className="empty-copy">Loading the task…</p>}
        </section>

        <section className="activity-panel">
          <div className="panel-heading"><span className="panel-label">Activity</span></div>
          <div className="activity-feed" ref={feedRef} aria-live="polite">
            {events.filter(displayEvent).slice(-120).map((event) => (
              <EventItem event={event} key={event.seq} labels={commandLabels} />
            ))}
            {!events.length && <div className="empty-feed"><span>·</span><p>No activity yet.</p></div>}
          </div>
        </section>

        <section className="workbench-panel">
          <div className="panel-heading">
            <span className="panel-label">Actions</span>
            <span className={`input-state ${run.awaitingInput ? "ready" : "busy"}`}>{run.awaitingInput ? "Your turn" : complete ? "Complete" : "Waiting"}</span>
          </div>
          <FriendlyBench endpoints={endpoints} roster={roster} pool={pool} disabled={disabled} onSubmit={submit} surface={surface} />
        </section>
      </div>
    </main>
  );
}

function TextBlock({ label, text, prominent = false }: { label: string; text: string; prominent?: boolean }) {
  return <div className={`text-block ${prominent ? "prominent" : ""}`}><h3>{label}</h3><pre>{text}</pre></div>;
}

function ConversationBrief({ text }: { text: string }) {
  const parsed = useMemo(() => parseConversationContext(text), [text]);
  if (!parsed.messages.length) return <TextBlock label="Earlier conversation" text={text} />;

  return (
    <section className="conversation-brief" aria-labelledby="conversation-heading">
      <div className="brief-section-heading">
        <div>
          <h3 id="conversation-heading">Earlier conversation</h3>
          <p>Messages relevant to this task.</p>
        </div>
        <span>{parsed.messages.length} messages</span>
      </div>

      <div className="brief-people" aria-label="People in this workspace">
        {parsed.people.map((person, index) => (
          <div className="brief-person" key={person.email || person.name}>
            <span className={`person-avatar tone-${index % 3}`}>{initials(person.name)}</span>
            <span><strong>{person.name}</strong><small>{person.role}</small></span>
          </div>
        ))}
      </div>

      <div className="transcript-thread">
        {parsed.messages.map((message, index) => {
          const personIndex = Math.max(0, parsed.people.findIndex((person) => person.name === message.sender.name));
          return (
            <article className="transcript-message" key={`${message.sender.id}-${index}`}>
              <span className={`person-avatar tone-${personIndex % 3}`}>{initials(message.sender.name)}</span>
              <div className="transcript-bubble">
                <header><strong>{message.sender.name}</strong><span>{message.sender.role}</span></header>
                <p>{message.text}</p>
              </div>
            </article>
          );
        })}
      </div>
      {parsed.remainder && <pre className="conversation-remainder">{parsed.remainder}</pre>}
    </section>
  );
}

function TaskBrief({ text, requester }: { text: string; requester: string }) {
  return (
    <section className="task-brief" aria-labelledby="task-heading">
      <div className="task-brief-meta">
        <span className="task-icon">→</span>
        <span><strong id="task-heading">Request</strong>{requester && <small>From {requester}</small>}</span>
      </div>
      <p>{text}</p>
    </section>
  );
}

function displayEvent(event: RunEvent) {
  if (event.type === "output" && !event.text?.trim()) return false;
  if (["output", "log", "status"].includes(event.type) && isHarnessChrome(event.text || "")) return false;
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

function EventItem({ event, labels }: { event: RunEvent; labels?: Record<string, string> }) {
  const time = new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (event.type === "turn") {
    return <article className="event-item turn-event"><div className="event-glyph">↳</div><div><header><strong>Task started</strong><time>{time}</time></header><p>{titleFromId(event.scenario || "task")}</p></div></article>;
  }
  if (event.type === "correction") {
    return <article className="event-item correction-event"><div className="event-glyph">!</div><div><header><strong>{event.sender ? `${event.sender} interrupts` : "Interruption"}</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  }
  if (event.type === "action") {
    const label = describeCommand(event.command || "", labels);
    return (
      <article className="event-item action-event">
        <div className="event-glyph">→</div>
        <div>
          <header><strong>You</strong><time>{time}</time></header>
          <p>{label}</p>
        </div>
      </article>
    );
  }
  if (event.type === "error") {
    return <article className="event-item error-event"><div className="event-glyph">×</div><div><header><strong>Task error</strong><time>{time}</time></header><p>{event.text}</p></div></article>;
  }
  if (event.type === "input_required") {
    return <article className="event-item input_required-event"><div className="event-glyph">·</div><div><header><strong>Your turn</strong><time>{time}</time></header></div></article>;
  }
  const text = event.text || event.status || "Run updated";
  return (
    <article className={`event-item ${event.type}-event`}>
      <div className="event-glyph">·</div>
      <div>
        <header><strong>{event.type === "status" ? "Status" : "Result"}</strong><time>{time}</time></header>
        <ResultView text={text} />
      </div>
    </article>
  );
}

function Completion({ run }: { run: RunSnapshot }) {
  const measured = run.status === "complete";
  const credited = run.exitCode === 0;
  return (
    <section className={`completion ${run.status}`}>
      <div className="completion-mark">{measured ? (credited ? "✓" : "≈") : "×"}</div>
      <div>
        <span>{measured ? "Benchmark complete" : "Benchmark stopped"}</span>
        <h2>{measured ? (credited ? "All tasks passed." : "One or more tasks did not pass.") : run.error || "No result was recorded."}</h2>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * Friendly workbench: the same commands, composed from labelled forms that
 * are derived mechanically from the request text every arm receives.
 * ------------------------------------------------------------------------- */

type Pool = ReturnType<typeof collectSuggestions>;

function FriendlyBench({ endpoints, roster, pool, disabled, onSubmit, surface }: {
  endpoints: Endpoint[];
  roster: { id: string; label: string }[];
  pool: Pool;
  disabled: boolean;
  onSubmit: (command: string) => Promise<void>;
  surface?: Surface | null;
}) {
  const lookups = endpoints.filter((e) => e.method === "GET");
  const actions = endpoints.filter((e) => e.method === "POST");
  return (
    <div className="friendly-bench">
      {surface ? (
        <SurfaceSections surface={surface} disabled={disabled} onSubmit={onSubmit} />
      ) : (
        <>
          {lookups.length > 0 && (
            <section className="bench-section">
              <h3>Look things up</h3>
              <p className="bench-hint">Search the workspace for information relevant to the request.</p>
              {lookups.map((endpoint) => <LookupCard key={endpoint.method + endpoint.path} endpoint={endpoint} disabled={disabled} onSubmit={onSubmit} />)}
            </section>
          )}
          {actions.length > 0 && (
            <section className="bench-section">
              <h3>Take an action</h3>
              <p className="bench-hint">Send messages, schedule work or use another available workplace action.</p>
              {actions.map((endpoint) => <ActionCard key={endpoint.method + endpoint.path} endpoint={endpoint} pool={pool} disabled={disabled} onSubmit={onSubmit} />)}
            </section>
          )}
        </>
      )}
      {(!surface || surface.ask) && (
        <section className="bench-section">
          <h3>Ask someone</h3>
          <p className="bench-hint">Ask a relevant person when the request or context is unclear.</p>
          <AskCard roster={roster} disabled={disabled} onSubmit={onSubmit} />
        </section>
      )}
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
      body[field.key] =
        field.kind === "list"
          ? raw.split(",").map((s) => s.trim()).filter(Boolean)
          : field.kind === "number"
            ? Number(raw)
            : field.kind === "bool"
              ? raw === "true"
              : raw;
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
  if (field.kind === "number") {
    return (
      <label className="stacked-field">
        <span>{label}</span>
        <input type="number" inputMode="numeric" step="any" value={value} onChange={(event) => onChange(event.target.value)} placeholder={field.hint} />
      </label>
    );
  }
  if (field.kind === "bool") {
    return (
      <label className="stacked-field">
        <span>{label}</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Choose…</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
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

export default App;
