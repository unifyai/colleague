export type Scenario = {
  id: string;
  title: string;
  description: string;
  available: boolean;
  limitation: string | null;
};

export type Benchmark = {
  kind: "conversational" | "standing" | "usecase";
  id: string;
  title: string;
  family: string;
  description: string;
  scenarios: Scenario[];
  available: boolean;
  limitation: string | null;
};

export type Family = { name: string; benchmarks: Benchmark[] };
export type Catalog = { families: Family[]; benchmarks: Benchmark[] };
export type AppConfig = { mutationToken: string };

export type CreateRunRequest = {
  kind: Benchmark["kind"];
  benchmark: string;
  scenario?: string;
  participantEmail: string;
};

/**
 * A participant surface: the office-language rendering of one task, authored
 * in Python beside the fixture it mirrors (see
 * colleague/tracks/standing/human_brief.py). The forms compose exactly the
 * /get and /post commands a terminal participant would type.
 */
export type SurfaceParam = {
  name: string;
  label: string;
  kind: string;
  hint?: string;
};

export type SurfaceField = {
  key: string;
  label: string;
  kind: string;
  hint?: string;
  options?: string[];
  columns?: SurfaceField[];
  fields?: SurfaceField[];
  key_label?: string;
  value_label?: string;
  value_kind?: string;
  allow_empty?: boolean;
  /** rows only: send each row as a list in cell order, not an object. */
  as_lists?: boolean;
};

export type SurfaceLookup = {
  label: string;
  description?: string;
  path: string;
  params: SurfaceParam[];
};

export type SurfaceAction = {
  label: string;
  description?: string;
  path: string;
  fields: SurfaceField[];
};

export type Surface = {
  title: string;
  brief: string;
  request?: string;
  lookups: SurfaceLookup[];
  actions: SurfaceAction[];
  hold: { path: string; label: string; description: string } | null;
  ask: boolean;
};

export type RunEvent = {
  seq: number;
  at: string;
  type: string;
  text?: string;
  status?: string;
  command?: string;
  prompt?: string;
  scenario?: string;
  sender?: string | null;
  context?: string | null;
  request?: string;
  images?: string[];
  surface?: Surface | null;
  result_path?: string | null;
};

export type RunSnapshot = {
  id: string;
  request: {
    kind: Benchmark["kind"];
    benchmark: string;
    scenario?: string;
    participantEmail: string;
  };
  status: "queued" | "running" | "complete" | "error";
  exitCode: number | null;
  error: string | null;
  resultPath: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  elapsedSeconds: number;
  awaitingInput: boolean;
  events: RunEvent[];
  lastSeq: number;
};
