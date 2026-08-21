/*
 * Rendering for participant surfaces — the office-language skin of a task.
 *
 * A surface is authored in Python beside the fixture it mirrors and arrives
 * on the turn event. Nothing here invents content: the brief text, the form
 * labels and the field lists all come from the surface, and submitting a
 * form composes exactly the /get or /post command a terminal participant
 * would type — with values typed the way the task contract expects them
 * (whole numbers stay whole numbers, groups nest, row lists become lists).
 */

import { FormEvent, useState } from "react";
import type { Surface, SurfaceAction, SurfaceField, SurfaceLookup, SurfaceParam } from "./types";

type Submit = (command: string) => Promise<void>;

/* ------------------------------------------------------------------ values */

type PairState = { key: string; value: string };
type RowState = Record<string, string>;
interface GroupState {
  [key: string]: FieldState;
}
type FieldState = string | boolean | PairState[] | RowState[] | GroupState;

function emptyState(field: SurfaceField): FieldState {
  if (field.kind === "pairs") return [{ key: "", value: "" }];
  if (field.kind === "rows") return [];
  if (field.kind === "bool") return false;
  if (field.kind === "group") {
    const group: GroupState = {};
    for (const inner of field.fields || []) group[inner.key] = emptyState(inner);
    return group;
  }
  return "";
}

function emptyAction(action: SurfaceAction): GroupState {
  const state: GroupState = {};
  for (const field of action.fields) state[field.key] = emptyState(field);
  return state;
}

type Built = { ok: boolean; value?: unknown };

function buildScalar(kind: string, raw: string, allowEmpty: boolean): Built {
  const trimmed = raw.trim();
  if (!trimmed) return allowEmpty ? { ok: true, value: kind === "list" ? [] : "" } : { ok: false };
  if (kind === "int") {
    if (!/^-?\d+$/.test(trimmed)) return { ok: false };
    return { ok: true, value: parseInt(trimmed, 10) };
  }
  if (kind === "float") {
    const value = Number(trimmed);
    return Number.isFinite(value) ? { ok: true, value } : { ok: false };
  }
  if (kind === "list") {
    return { ok: true, value: trimmed.split(",").map((s) => s.trim()).filter(Boolean) };
  }
  return { ok: true, value: trimmed };
}

function buildField(field: SurfaceField, state: FieldState): Built {
  if (field.kind === "bool") return { ok: true, value: Boolean(state) };
  if (field.kind === "group") {
    const group = (state || {}) as GroupState;
    const value: Record<string, unknown> = {};
    for (const inner of field.fields || []) {
      const built = buildField(inner, group[inner.key]);
      if (!built.ok) return { ok: false };
      value[inner.key] = built.value;
    }
    return { ok: true, value };
  }
  if (field.kind === "pairs") {
    const pairs = ((state || []) as PairState[]).filter((p) => p.key.trim());
    if (!pairs.length) return field.allow_empty ? { ok: true, value: {} } : { ok: false };
    const value: Record<string, unknown> = {};
    for (const pair of pairs) {
      const built = buildScalar(field.value_kind || "int", pair.value, false);
      if (!built.ok) return { ok: false };
      value[pair.key.trim()] = built.value;
    }
    return { ok: true, value };
  }
  if (field.kind === "rows") {
    const rows = (state || []) as RowState[];
    if (!rows.length) return field.allow_empty ? { ok: true, value: [] } : { ok: false };
    const value: Record<string, unknown>[] = [];
    for (const row of rows) {
      const out: Record<string, unknown> = {};
      for (const column of field.columns || []) {
        const built = buildScalar(column.kind, row[column.key] || "", false);
        if (!built.ok) return { ok: false };
        out[column.key] = built.value;
      }
      value.push(out);
    }
    return { ok: true, value };
  }
  return buildScalar(field.kind, String(state ?? ""), Boolean(field.allow_empty));
}

function buildBody(action: SurfaceAction, state: GroupState): Built {
  const body: Record<string, unknown> = {};
  for (const field of action.fields) {
    const built = buildField(field, state[field.key]);
    if (!built.ok) return { ok: false };
    body[field.key] = built.value;
  }
  return { ok: true, value: body };
}

/* ---------------------------------------------------------------- controls */

function ScalarControl({ kind, value, hint, onChange }: { kind: string; value: string; hint?: string; onChange: (next: string) => void }) {
  if (kind === "long") return <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} placeholder={hint} />;
  if (kind === "date") return <input type="date" value={value} onChange={(e) => onChange(e.target.value)} />;
  if (kind === "int" || kind === "float") {
    return (
      <input
        type="number"
        inputMode={kind === "int" ? "numeric" : "decimal"}
        step={kind === "int" ? 1 : "any"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={hint}
      />
    );
  }
  if (kind === "email") return <input type="email" value={value} onChange={(e) => onChange(e.target.value)} placeholder={hint} />;
  return <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={hint} />;
}

function FieldControl({ field, state, onChange }: { field: SurfaceField; state: FieldState; onChange: (next: FieldState) => void }) {
  if (field.kind === "choice") {
    return (
      <label className="stacked-field">
        <span>{field.label}</span>
        <select value={String(state || "")} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose…</option>
          {(field.options || []).map((option) => (
            <option key={option} value={option}>{option.replace(/_/g, " ")}</option>
          ))}
        </select>
      </label>
    );
  }
  if (field.kind === "bool") {
    return (
      <label className="check-field">
        <input type="checkbox" checked={Boolean(state)} onChange={(e) => onChange(e.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  if (field.kind === "group") {
    const group = (state || {}) as GroupState;
    return (
      <fieldset className="surface-group">
        <legend>{field.label}</legend>
        {(field.fields || []).map((inner) => (
          <FieldControl
            key={inner.key}
            field={inner}
            state={group[inner.key] ?? emptyState(inner)}
            onChange={(next) => onChange({ ...group, [inner.key]: next })}
          />
        ))}
      </fieldset>
    );
  }
  if (field.kind === "pairs") {
    const pairs = (state || []) as PairState[];
    const update = (index: number, next: Partial<PairState>) =>
      onChange(pairs.map((pair, i) => (i === index ? { ...pair, ...next } : pair)));
    return (
      <fieldset className="surface-group">
        <legend>{field.label}</legend>
        {pairs.map((pair, index) => (
          <div className="surface-row" key={index}>
            <input value={pair.key} onChange={(e) => update(index, { key: e.target.value })} placeholder={field.key_label || "Name"} aria-label={field.key_label || "Name"} />
            <ScalarControl kind={field.value_kind || "int"} value={pair.value} hint={field.value_label} onChange={(next) => update(index, { value: next })} />
            <button type="button" className="row-remove" aria-label="Remove" onClick={() => onChange(pairs.filter((_, i) => i !== index))}>×</button>
          </div>
        ))}
        <button type="button" className="quiet-button" onClick={() => onChange([...pairs, { key: "", value: "" }])}>
          Add {field.key_label ? field.key_label.toLowerCase() : "entry"}
        </button>
      </fieldset>
    );
  }
  if (field.kind === "rows") {
    const rows = (state || []) as RowState[];
    const columns = field.columns || [];
    const update = (index: number, key: string, next: string) =>
      onChange(rows.map((row, i) => (i === index ? { ...row, [key]: next } : row)));
    return (
      <fieldset className="surface-group">
        <legend>{field.label}</legend>
        {rows.map((row, index) => (
          <div className="surface-row" key={index}>
            {columns.map((column) =>
              column.kind === "choice" ? (
                <select key={column.key} value={row[column.key] || ""} onChange={(e) => update(index, column.key, e.target.value)} aria-label={column.label}>
                  <option value="">{column.label}…</option>
                  {(column.options || []).map((option) => (
                    <option key={option} value={option}>{option.replace(/_/g, " ")}</option>
                  ))}
                </select>
              ) : (
                <ScalarControl key={column.key} kind={column.kind} value={row[column.key] || ""} hint={column.label} onChange={(next) => update(index, column.key, next)} />
              ),
            )}
            <button type="button" className="row-remove" aria-label="Remove row" onClick={() => onChange(rows.filter((_, i) => i !== index))}>×</button>
          </div>
        ))}
        <button type="button" className="quiet-button" onClick={() => onChange([...rows, {}])}>Add row</button>
      </fieldset>
    );
  }
  return (
    <label className="stacked-field">
      <span>{field.label}{field.allow_empty ? "" : ""}</span>
      <ScalarControl kind={field.kind} value={String(state ?? "")} hint={field.hint} onChange={(next) => onChange(next)} />
    </label>
  );
}

/* ------------------------------------------------------------------- cards */

function SurfaceLookupCard({ lookup, disabled, onSubmit }: { lookup: SurfaceLookup; disabled: boolean; onSubmit: Submit }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const missing = lookup.params.some((param) => !(values[param.name] || "").trim());

  function buildPath(): string {
    let path = lookup.path;
    const query: string[] = [];
    for (const param of lookup.params) {
      const value = (values[param.name] || "").trim();
      if (path.includes(`<${param.name}>`)) {
        path = path.replace(`<${param.name}>`, encodeURIComponent(value));
      } else {
        query.push(`${param.name}=${encodeURIComponent(value)}`);
      }
    }
    return query.length ? `${path}?${query.join("&")}` : path;
  }

  return (
    <form className="bench-card" onSubmit={(event) => { event.preventDefault(); onSubmit(`/get ${buildPath()}`); }}>
      <div className="bench-card-row">
        <div className="bench-card-title">
          <strong>{lookup.label}</strong>
          {lookup.description && <small>{lookup.description}</small>}
        </div>
        {lookup.params.map((param: SurfaceParam) => (
          <label className="inline-field" key={param.name}>
            <span>{param.label}</span>
            <ScalarControl kind={param.kind} value={values[param.name] || ""} hint={param.hint} onChange={(next) => setValues((v) => ({ ...v, [param.name]: next }))} />
          </label>
        ))}
        <button className="bench-go" disabled={disabled || missing}>Look</button>
      </div>
    </form>
  );
}

function SurfaceActionCard({ action, disabled, onSubmit }: { action: SurfaceAction; disabled: boolean; onSubmit: Submit }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<GroupState>(() => emptyAction(action));
  const built = buildBody(action, state);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!built.ok) return;
    await onSubmit(`/post ${action.path} ${JSON.stringify(built.value)}`);
    setOpen(false);
    setState(emptyAction(action));
  }

  if (!open) {
    return (
      <button className="bench-card bench-card-closed" type="button" disabled={disabled} onClick={() => setOpen(true)}>
        <strong>{action.label}</strong>
        {action.description && <small>{action.description}</small>}
        <span className="open-marker">＋</span>
      </button>
    );
  }
  return (
    <form className="bench-card bench-card-open" onSubmit={submit}>
      <div className="bench-card-title">
        <strong>{action.label}</strong>
        {action.description && <small>{action.description}</small>}
      </div>
      {action.fields.map((field) => (
        <FieldControl key={field.key} field={field} state={state[field.key] ?? emptyState(field)} onChange={(next) => setState((s: GroupState) => ({ ...s, [field.key]: next }))} />
      ))}
      <div className="bench-card-actions">
        <button type="button" className="quiet-button" onClick={() => setOpen(false)}>Cancel</button>
        <button className="bench-go" disabled={disabled || !built.ok}>{action.label}</button>
      </div>
    </form>
  );
}

function HoldCard({ hold, disabled, onSubmit }: { hold: NonNullable<Surface["hold"]>; disabled: boolean; onSubmit: Submit }) {
  const [reason, setReason] = useState("");
  return (
    <form
      className="bench-card bench-card-open hold-card"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(`/post ${hold.path} ${JSON.stringify({ message: `HOLD: ${reason.trim()}` })}`);
        setReason("");
      }}
    >
      <div className="bench-card-title">
        <strong>{hold.label}</strong>
        <small>{hold.description}</small>
      </div>
      <label className="stacked-field">
        <span>What you saw, and why you stopped</span>
        <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="The amounts no longer look like cents…" />
      </label>
      <button className="bench-go" disabled={disabled || !reason.trim()}>Hold and tell the owner</button>
    </form>
  );
}

/* ----------------------------------------------------------------- exports */

export function SurfaceBrief({ surface }: { surface: Surface }) {
  return (
    <section className="task-brief surface-brief" aria-labelledby="surface-heading">
      <div className="task-brief-meta">
        <span className="task-icon">☰</span>
        <span><strong id="surface-heading">{surface.title}</strong><small>Your standing brief</small></span>
      </div>
      {surface.brief.split(/\n{2,}/).map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </section>
  );
}

export function SurfaceRequest({ surface }: { surface: Surface }) {
  if (!surface.request) return null;
  return (
    <section className="task-brief" aria-labelledby="surface-request-heading">
      <div className="task-brief-meta">
        <span className="task-icon">→</span>
        <span><strong id="surface-request-heading">Right now</strong></span>
      </div>
      <p>{surface.request}</p>
    </section>
  );
}

export function SurfaceSections({ surface, disabled, onSubmit }: { surface: Surface; disabled: boolean; onSubmit: Submit }) {
  return (
    <>
      {surface.lookups.length > 0 && (
        <section className="bench-section">
          <h3>Look things up</h3>
          <p className="bench-hint">The workspace information this work draws on.</p>
          {surface.lookups.map((lookup) => (
            <SurfaceLookupCard key={lookup.path + lookup.label} lookup={lookup} disabled={disabled} onSubmit={onSubmit} />
          ))}
        </section>
      )}
      {surface.actions.length > 0 && (
        <section className="bench-section">
          <h3>Take an action</h3>
          <p className="bench-hint">What this work delivers.</p>
          {surface.actions.map((action) => (
            <SurfaceActionCard key={action.path + action.label} action={action} disabled={disabled} onSubmit={onSubmit} />
          ))}
        </section>
      )}
      {surface.hold && (
        <section className="bench-section">
          <h3>Something is wrong?</h3>
          <HoldCard hold={surface.hold} disabled={disabled} onSubmit={onSubmit} />
        </section>
      )}
    </>
  );
}
