"use client";

import { FormEvent, useState } from "react";

type SourceStatus = {
  project_id: string;
  source_id: string;
  source_title?: string | null;
  enabled: boolean;
  status: string;
  persisted_status: string;
  current_file_hash?: string | null;
  indexed_file_hash?: string | null;
  stale: boolean;
  point_count: number;
  indexed_run_id?: string | null;
  indexed_at?: string | null;
  rebuild_requested_at?: string | null;
  last_error?: string | null;
  file_error?: string | null;
  qdrant_available?: boolean | null;
  qdrant_error?: string | null;
};

type HealthStatus = {
  qdrant?: { status?: string; available?: boolean; detail?: string };
  colsmol?: { status?: string; available?: boolean; detail?: string };
};

const API_ROOT = "/api/drawing-extractions/multivector";

function sourceEndpoint(projectId: string, sourceId: string, action?: string) {
  const base = `${API_ROOT}/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}`;
  return action ? `${base}/${action}` : base;
}

function readableStatus(status: string) {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function responseError(response: Response) {
  try {
    const body = await response.json();
    return typeof body.detail === "string"
      ? body.detail
      : JSON.stringify(body.detail ?? body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export default function MultiVectorPage() {
  const [projectId, setProjectId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [status, setStatus] = useState<SourceStatus | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const hasIds = projectId.trim().length > 0 && sourceId.trim().length > 0;

  async function runRequest(method: "GET" | "POST", action?: string) {
    if (!hasIds) {
      setMessage("Enter both a project ID and source ID.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(
        sourceEndpoint(projectId.trim(), sourceId.trim(), action),
        { method },
      );
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const body = (await response.json()) as SourceStatus;
      setStatus(body);
      setMessage(action ? `${readableStatus(action)} completed.` : "Status refreshed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function checkHealth() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_ROOT}/health`);
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      setHealth((await response.json()) as HealthStatus);
      setMessage("Service health refreshed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Health check failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitStatus(event: FormEvent) {
    event.preventDefault();
    await runRequest("GET");
  }

  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground sm:px-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <header className="space-y-2">
          <div className="inline-flex rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Experimental
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Multi-vector drawing index</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Opt individual project sources into visual retrieval, inspect stale-file state,
            and queue a clean source rebuild without changing normal source ingestion.
          </p>
        </header>

        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <form className="grid gap-4 md:grid-cols-2" onSubmit={submitStatus}>
            <label className="space-y-2 text-sm font-medium">
              Project ID
              <input
                aria-label="Project ID"
                className="w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
                onChange={(event) => setProjectId(event.target.value)}
                placeholder="project:..."
                value={projectId}
              />
            </label>
            <label className="space-y-2 text-sm font-medium">
              Source ID
              <input
                aria-label="Source ID"
                className="w-full rounded-md border bg-background px-3 py-2 font-mono text-sm"
                onChange={(event) => setSourceId(event.target.value)}
                placeholder="source:..."
                value={sourceId}
              />
            </label>
            <div className="flex flex-wrap gap-2 md:col-span-2">
              <button
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                disabled={busy || !hasIds}
                type="submit"
              >
                Load status
              </button>
              <button
                className="rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
                disabled={busy || !hasIds}
                onClick={() => runRequest("POST", "enable")}
                type="button"
              >
                Enable
              </button>
              <button
                className="rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
                disabled={busy || !hasIds}
                onClick={() => runRequest("POST", "disable")}
                type="button"
              >
                Disable
              </button>
              <button
                className="rounded-md border border-amber-500/60 px-4 py-2 text-sm font-medium disabled:opacity-50"
                disabled={busy || !hasIds}
                onClick={() => runRequest("POST", "rebuild")}
                type="button"
              >
                Queue rebuild
              </button>
              <button
                className="rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
                disabled={busy}
                onClick={checkHealth}
                type="button"
              >
                Check services
              </button>
            </div>
          </form>
          {message ? (
            <p aria-live="polite" className="mt-4 rounded-md bg-muted px-3 py-2 text-sm">
              {message}
            </p>
          ) : null}
        </section>

        {health ? (
          <section className="grid gap-4 sm:grid-cols-2" aria-label="Service health">
            {(["qdrant", "colsmol"] as const).map((service) => (
              <div className="rounded-xl border bg-card p-4" key={service}>
                <div className="text-sm font-medium capitalize">{service}</div>
                <div className="mt-1 text-2xl font-semibold">
                  {readableStatus(health[service]?.status ?? "unknown")}
                </div>
                {health[service]?.detail ? (
                  <p className="mt-2 text-xs text-muted-foreground">{health[service]?.detail}</p>
                ) : null}
              </div>
            ))}
          </section>
        ) : null}

        {status ? (
          <section className="rounded-xl border bg-card p-5 shadow-sm" aria-label="Source index status">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm text-muted-foreground">{status.source_title || status.source_id}</p>
                <h2 className="text-2xl font-semibold">{readableStatus(status.status)}</h2>
              </div>
              <span className="rounded-full border px-3 py-1 text-xs font-medium">
                {status.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <StatusField label="Qdrant points" value={String(status.point_count)} />
              <StatusField label="Stale file" value={status.stale ? "Yes" : "No"} />
              <StatusField
                label="Qdrant available"
                value={status.qdrant_available == null ? "Not checked" : status.qdrant_available ? "Yes" : "No"}
              />
              <StatusField label="Indexed run" value={status.indexed_run_id || "None"} mono />
              <StatusField label="Current file hash" value={status.current_file_hash || "Unavailable"} mono />
              <StatusField label="Indexed file hash" value={status.indexed_file_hash || "None"} mono />
            </dl>

            {status.last_error || status.file_error || status.qdrant_error ? (
              <div className="mt-5 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
                {status.last_error || status.file_error || status.qdrant_error}
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </main>
  );
}

function StatusField({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/50 p-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={`mt-1 break-all text-sm ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
