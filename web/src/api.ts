import type { AppConfig, Catalog, CreateRunRequest, RunSnapshot } from "./types";

let mutationToken = "";

async function checked<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body as T;
}

export async function initialize(): Promise<{ config: AppConfig; catalog: Catalog }> {
  const [config, catalog] = await Promise.all([
    checked<AppConfig>(await fetch("/api/config")),
    checked<Catalog>(await fetch("/api/catalog")),
  ]);
  mutationToken = config.mutationToken;
  return { config, catalog };
}

export async function createRun(request: CreateRunRequest): Promise<RunSnapshot> {
  return checked(
    await fetch("/api/runs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Colleague-Token": mutationToken,
      },
      body: JSON.stringify(request),
    }),
  );
}

export async function getRun(id: string, after = 0): Promise<RunSnapshot> {
  return checked(await fetch(`/api/runs/${id}?after=${after}`, { cache: "no-store" }));
}

export async function sendAction(id: string, command: string): Promise<void> {
  await checked(
    await fetch(`/api/runs/${id}/actions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Colleague-Token": mutationToken,
      },
      body: JSON.stringify({ command }),
    }),
  );
}

export function runFileUrl(id: string, path: string): string {
  return `/api/runs/${id}/file?path=${encodeURIComponent(path)}`;
}
