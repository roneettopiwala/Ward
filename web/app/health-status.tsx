"use client";

import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ServiceStatus = { ok: boolean; detail: string | null };
type DatabaseStatus = ServiceStatus & { postgis_version: string | null };
type HealthResponse = {
  api: ServiceStatus;
  database: DatabaseStatus;
  redis: ServiceStatus;
};

type Row = { name: string; ok: boolean | null; info: string | null };

function StatusRow({ name, ok, info }: Row) {
  const dot = ok === null ? "bg-zinc-400" : ok ? "bg-green-500" : "bg-red-500";
  return (
    <li className="flex items-start gap-3 rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${dot}`} />
      <div className="min-w-0">
        <p className="font-medium">{name}</p>
        {info && <p className="break-words text-sm text-zinc-500">{info}</p>}
      </div>
    </li>
  );
}

export default function HealthStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const check = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setHealth((await res.json()) as HealthResponse);
      setError(null);
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch on mount
    void check();
  }, [check]);

  const rows: Row[] = health
    ? [
        { name: "API", ok: health.api.ok, info: API_URL },
        {
          name: "Postgres",
          ok: health.database.ok,
          info: health.database.ok
            ? `PostGIS ${health.database.postgis_version}`
            : health.database.detail,
        },
        { name: "Redis", ok: health.redis.ok, info: health.redis.detail },
      ]
    : [
        { name: "API", ok: loading ? null : false, info: error ?? API_URL },
        { name: "Postgres", ok: null, info: null },
        { name: "Redis", ok: null, info: null },
      ];

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">System status</h2>
        <button
          type="button"
          onClick={() => void check()}
          disabled={loading}
          className="rounded-md border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          {loading ? "Checking…" : "Refresh"}
        </button>
      </div>
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <StatusRow key={row.name} {...row} />
        ))}
      </ul>
    </section>
  );
}
