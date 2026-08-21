/*
 * Mechanical reading of the fixture contract every arm receives.
 *
 * The request text shown to a participant contains the same API block the
 * machine arms get. This module parses that block — nothing else — so the
 * workbench can render each endpoint as a labelled form instead of a raw
 * path-and-JSON box. It derives strictly from text the participant can
 * already read, so it adds usability, never information; the composed
 * commands are byte-equivalent to what a terminal participant would type.
 * Anything the parser cannot read simply falls back to the technical view.
 */

export type Param = {
  name: string;
  hint: string;
  optional: boolean;
};

export type BodyField = {
  key: string;
  label: string;
  hint: string;
  optional: boolean;
  options: string[] | null;
  kind: "text" | "long" | "date" | "list";
};

export type Endpoint = {
  method: "GET" | "POST";
  path: string;
  label: string;
  pathParams: Param[];
  queryParams: Param[];
  fields: BodyField[];
  note: string;
};

const LINE = /^\s*(GET|POST)\s+(\S+)(?:\s*->\s*(.*))?$/;

function humanize(value: string): string {
  const cleaned = value.replace(/_id$/, "").replace(/[_-]+/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function placeholderParam(name: string, raw: string): Param {
  const inner = raw.replace(/^<|>$/g, "");
  return {
    name,
    hint: inner.replace(/\?$/, ""),
    optional: /\?>?$/.test(raw.replace(/^</, "")),
  };
}

/** Fields that read better as a multi-line box than a single line. */
const LONG_KEYS = new Set(["text", "body", "question", "message", "note"]);

function parseField(key: string, spec: string): BodyField {
  const base = {
    key,
    label: humanize(key),
    hint: "",
    optional: false,
    options: null as string[] | null,
    kind: LONG_KEYS.has(key) ? ("long" as const) : ("text" as const),
  };
  const trimmed = spec.trim();
  if (trimmed.startsWith("[")) {
    const inner = /<([^>]+)>/.exec(trimmed);
    return {
      ...base,
      kind: "list",
      hint: inner ? `${inner[1]}, one per comma` : "comma-separated list",
    };
  }
  const parts = trimmed.split("|").map((p) => p.trim().replace(/^"|"$/g, ""));
  if (parts.length > 1) {
    const optional = parts.some((p) => p.endsWith("?"));
    return {
      ...base,
      optional,
      options: parts.map((p) => p.replace(/\?$/, "")),
    };
  }
  const value = parts[0];
  const optional = /\?>?$/.test(value) || value.endsWith("?");
  const hint = value.replace(/^<|>\??$/g, "").replace(/\?$/, "");
  if (/^Y{2,4}-?M{2}-?D{2}$/i.test(value)) {
    return { ...base, kind: "date", hint: value };
  }
  return { ...base, optional, hint };
}

function parseBody(spec: string): BodyField[] {
  const braces = spec.indexOf("{");
  if (braces < 0) return [];
  const inner = spec.slice(braces);
  const fields: BodyField[] = [];
  const pattern = /"(\w+)":\s*(\[[^\]]*\]|"[^"]*"(?:\s*\|\s*"[^"]*")*)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(inner)) !== null) {
    fields.push(parseField(match[1], match[2]));
  }
  return fields;
}

export function parseApiDoc(request: string): Endpoint[] {
  const endpoints: Endpoint[] = [];
  for (const line of request.split("\n")) {
    const match = LINE.exec(line);
    if (!match) continue;
    const method = match[1] as "GET" | "POST";
    const target = match[2];
    const shape = (match[3] || "").trim();
    let path: string;
    try {
      path = target.startsWith("http") ? new URL(target).pathname + (target.includes("?") ? "?" + target.split("?").slice(1).join("?") : "") : target;
    } catch {
      path = target;
    }
    const [rawPath, rawQuery = ""] = path.split("?");
    const pathParams: Param[] = [];
    for (const segment of rawPath.split("/")) {
      const placeholder = /^<(.+)>$/.exec(segment);
      if (placeholder) pathParams.push(placeholderParam(placeholder[1], segment));
    }
    const queryParams: Param[] = [];
    for (const pair of rawQuery.split("&").filter(Boolean)) {
      const [name, value = ""] = pair.split("=");
      if (value.startsWith("<")) queryParams.push(placeholderParam(name, value));
    }
    const fields = method === "POST" ? parseBody(shape) : [];
    const noteMatch = /\(([^)]+)\)\s*$/.exec(shape);
    const lastSegment = rawPath.split("/").filter((s) => s && !s.startsWith("<")).pop() || rawPath;
    endpoints.push({
      method,
      path: rawPath,
      label: humanize(lastSegment),
      pathParams,
      queryParams,
      fields,
      note: noteMatch ? noteMatch[1] : "",
    });
  }
  return endpoints;
}

export type RosterEntry = { id: string; label: string };

/**
 * People named in the shared context, for the ask-someone picker.
 * Recognises the two roster shapes the fixtures use:
 *   - Name (role), email@example
 *   [Name — role] said something…
 * The id an /ask must carry is the email local part where an email is
 * given, else the lower-cased first name — the same convention the
 * participant ids in every track follow.
 */
export function parseRoster(context: string): RosterEntry[] {
  const seen = new Map<string, RosterEntry>();
  const bullet = /^\s*[-•]\s*([^(]+?)\s*\(([^)]+)\)\s*,\s*(\S+@\S+)/;
  const spoken = /^\s*\[([^\]—-]+?)\s*[—-]\s*([^\]]+)\]/;
  for (const line of context.split("\n")) {
    let name = "";
    let role = "";
    let id = "";
    const b = bullet.exec(line);
    const s = spoken.exec(line);
    if (b) {
      name = b[1].trim();
      role = b[2].trim();
      id = b[3].split("@")[0].toLowerCase();
    } else if (s) {
      name = s[1].trim();
      role = s[2].trim();
      id = name.split(/\s+/)[0].toLowerCase();
    } else {
      continue;
    }
    if (!seen.has(id)) seen.set(id, { id, label: role ? `${name} — ${role}` : name });
  }
  return [...seen.values()];
}

/** A short human reading of a workbench command, for the activity feed. */
export function describeCommand(command: string): string {
  if (command.startsWith("/get ")) return `Looked at ${humanize(command.slice(5).trim().split("?")[0].split("/").filter(Boolean).pop() || "the workspace").toLowerCase()}`;
  if (command.startsWith("/post ")) {
    const path = command.slice(6).trim().split(/\s/)[0];
    return humanize(path.split("/").filter(Boolean).pop() || "action");
  }
  if (command.startsWith("/ask ")) {
    const rest = command.slice(5).trim();
    return `Asked ${humanize(rest.split(/\s+/)[0])}`;
  }
  if (command.startsWith("/note")) return "Saved a note";
  if (command.startsWith("/done")) return "Finished the task";
  return command;
}

/**
 * Values the participant has already seen in lookup results this run,
 * offered back as type-ahead suggestions. Only what their own requests
 * returned — the pool starts empty and the scorers still see every GET.
 */
export function collectSuggestions(jsonTexts: string[]): { emails: string[]; ids: string[]; names: string[] } {
  const emails = new Set<string>();
  const ids = new Set<string>();
  const names = new Set<string>();
  const walk = (value: unknown, key: string) => {
    if (typeof value === "string") {
      if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) emails.add(value);
      else if (/id$/i.test(key) || /^(id)$/.test(key)) ids.add(value);
      else if (/^name$/i.test(key) || /^(to|who|assignee)$/i.test(key)) names.add(value);
    } else if (Array.isArray(value)) {
      value.forEach((item) => walk(item, key));
    } else if (value && typeof value === "object") {
      Object.entries(value).forEach(([k, v]) => walk(v, k));
    }
  };
  for (const text of jsonTexts) {
    try {
      walk(JSON.parse(text), "");
    } catch {
      /* not JSON — nothing to collect */
    }
  }
  const cap = (set: Set<string>) => [...set].slice(0, 40);
  return { emails: cap(emails), ids: cap(ids), names: cap(names) };
}

/** Which suggestion pool suits a field, judged from its hint/key text. */
export function suggestionsFor(field: { key?: string; hint: string }, pool: { emails: string[]; ids: string[]; names: string[] }): string[] {
  const text = `${field.key || ""} ${field.hint}`.toLowerCase();
  if (text.includes("email")) return pool.emails;
  if (text.includes("id")) return pool.ids;
  if (/\b(to|person|who|name)\b/.test(text)) return [...pool.names, ...pool.emails, ...pool.ids].slice(0, 40);
  return [];
}
