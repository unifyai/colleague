export type Scenario = {
  id: string;
  title: string;
  description: string;
  tags: string;
  available: boolean;
  limitation: string | null;
};

export type Benchmark = {
  kind: "conversational" | "standing" | "usecase";
  id: string;
  title: string;
  family: string;
  description: string;
  tags?: string;
  modes: string[];
  scenarios: Scenario[];
  available: boolean;
  limitation: string | null;
};

export type Family = { name: string; benchmarks: Benchmark[] };
export type Catalog = { families: Family[]; benchmarks: Benchmark[] };

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
  cost?: Record<string, unknown>;
  result_path?: string | null;
};

export type RunSnapshot = {
  id: string;
  request: {
    kind: Benchmark["kind"];
    benchmark: string;
    scenario?: string;
    mode: string;
    participantId: string;
    hourlyRateUsd: number;
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
