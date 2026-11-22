"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Stat, Table, Td, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Job } from "@/lib/types";

const TABS = ["", "queued", "running", "failed", "succeeded"] as const;

export default function JobsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Job[]>(`/admin/jobs?limit=200${tab ? `&status_filter=${tab}` : ""}`).then(setJobs);
    api<Record<string, number>>("/admin/jobs/stats").then(setStats);
  }, [tab]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000); // live view while workers drain the queue
    return () => clearInterval(timer);
  }, [load]);

  async function run(key: string, fn: () => Promise<string>) {
    setBusy(key);
    try {
      setNotice({ tone: "green", text: await fn() });
      load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Factory jobs"
        description="Website generation runs on factory workers. Queue a batch of the top-scoring candidates."
        actions={
          <Button busy={busy === "batch"} onClick={() => run("batch", async () => {
            const r = await api<{ enqueued: number; skipped: number }>("/websites/generate-batch", { body: { limit: 100, publish: true } });
            return `Queued ${r.enqueued} sites (${r.skipped} already queued).`;
          })}>Queue factory batch</Button>
        }
      />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Queued" value={stats.queued ?? 0} />
        <Stat label="Running" value={stats.running ?? 0} />
        <Stat label="Succeeded" value={stats.succeeded ?? 0} />
        <Stat label="Failed" value={stats.failed ?? 0} />
      </div>
      <div className="mb-4 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
        {TABS.map((t) => (
          <button key={t || "all"} onClick={() => setTab(t)} className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium capitalize",
            tab === t ? "border-brand-600 text-ink" : "border-transparent text-stone-500 hover:text-ink",
          )}>{t || "all"}</button>
        ))}
      </div>
      <Card>
        {jobs.length === 0 ? <Empty>No jobs.</Empty> : (
          <Table head={["Job", "Status", "Attempts", "Worker", "Result / error", "Created", ""]}>
            {jobs.map((j) => (
              <tr key={j.id}>
                <Td>
                  <div className="font-medium">{j.kind.replaceAll("_", " ")}</div>
                  <div className="font-mono text-xs text-stone-500">{j.id.slice(0, 8)}</div>
                </Td>
                <Td><Badge tone={j.status === "succeeded" ? "green" : j.status === "failed" ? "red" : j.status === "running" ? "blue" : "gray"}>{j.status}</Badge></Td>
                <Td className="tabular-nums">{j.attempts}/{j.max_attempts}</Td>
                <Td className="font-mono text-xs text-stone-500">{j.locked_by ?? "—"}</Td>
                <Td className="max-w-80 truncate text-xs text-stone-600" >
                  <span title={j.last_error ?? JSON.stringify(j.result ?? {})}>
                    {j.last_error ?? (j.result ? Object.entries(j.result).map(([k, v]) => `${k}: ${v}`).join(" · ") : "—")}
                  </span>
                </Td>
                <Td className="whitespace-nowrap text-xs text-stone-500">{new Date(j.created_at).toLocaleString()}</Td>
                <Td className="text-right">
                  {j.status === "failed" && (
                    <Button size="sm" variant="secondary" busy={busy === j.id} onClick={() => run(j.id, async () => {
                      await api(`/admin/jobs/${j.id}/retry`, { body: {} });
                      return "Job re-queued.";
                    })}>Retry</Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
