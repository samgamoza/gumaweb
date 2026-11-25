"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useUser } from "@/components/auth-guard";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Table, Td, Textarea, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { DiscoveryCampaign, DiscoveryRun, DiscoverySourceInfo, EnrichmentTierInfo } from "@/lib/types";

type EnrichMode = "all" | "custom" | "none";

interface FormState {
  id: string | null;
  name: string;
  description: string;
  cities: string;
  categories: string;
  sources: string[];
  enrichMode: EnrichMode;
  tiers: string[];
  target: string;
  perQuery: string;
}

const EMPTY: FormState = {
  id: null, name: "", description: "", cities: "", categories: "", sources: ["osm"], enrichMode: "all", tiers: [],
  target: "100", perQuery: "50",
};

const ACTIVE = new Set(["queued", "running"]);
const CATEGORY_LABEL: Record<string, string> = { directory: "Directories", registry: "Registries", test: "Test data" };

/** "Cebu City, Davao City" or one per line -> ["Cebu City", "Davao City"]. */
function splitList(text: string): string[] {
  return text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

function toForm(c: DiscoveryCampaign): FormState {
  return {
    id: c.id, name: c.name, description: c.description ?? "", cities: c.cities.join("\n"),
    categories: c.categories.join("\n"), sources: c.sources,
    enrichMode: c.enrichment_tiers === null ? "all" : c.enrichment_tiers.length ? "custom" : "none",
    tiers: c.enrichment_tiers ?? [], target: String(c.target), perQuery: String(c.per_query),
  };
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function RunProgress({ run, onCancel, busy }: { run: DiscoveryRun; onCancel?: () => void; busy?: boolean }) {
  const p = run.progress ?? {};
  const done = p.queries_done ?? 0;
  const planned = Math.max(p.queries_planned ?? 0, 1);
  const pct = Math.min(100, Math.round((done / planned) * 100));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge>{run.status}</Badge>
          {run.cancel_requested && ACTIVE.has(run.status) && <Badge tone="amber">stopping after this query</Badge>}
          <span className="text-sm text-stone-600">{p.current ?? (run.status === "queued" ? "Waiting for a worker…" : "")}</span>
        </div>
        {onCancel && ACTIVE.has(run.status) && !run.cancel_requested && (
          <Button size="sm" variant="danger" busy={busy} onClick={onCancel}>Cancel sweep</Button>
        )}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-stone-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-stone-500">Queries</dt><dd className="tabular-nums">{done} / {p.queries_planned ?? 0}</dd></div>
        <div><dt className="text-xs text-stone-500">Found</dt><dd className="tabular-nums">{p.found ?? 0} / {p.target ?? "—"}</dd></div>
        <div><dt className="text-xs text-stone-500">Without a website</dt><dd className="tabular-nums">{p.prospects ?? 0}</dd></div>
        <div><dt className="text-xs text-stone-500">Imported</dt><dd className="tabular-nums">{run.created_count} new · {run.duplicate_count} dup</dd></div>
      </dl>
      {(p.warnings?.length ?? 0) > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-amber-800">{p.warnings!.length} quer{p.warnings!.length === 1 ? "y" : "ies"} failed (the sweep carried on)</summary>
          <ul className="mt-2 space-y-1 font-mono text-xs text-stone-600">{p.warnings!.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}
      {run.errors.length > 0 && run.status === "failed" && (
        <Alert tone="red">{run.errors.map((e) => e.error).join("; ")}</Alert>
      )}
    </div>
  );
}

function History({ campaignId }: { campaignId: string }) {
  const [runs, setRuns] = useState<DiscoveryRun[] | null>(null);
  useEffect(() => { api<DiscoveryRun[]>(`/discovery/campaigns/${campaignId}/runs`).then(setRuns); }, [campaignId]);
  if (!runs) return <div className="text-sm text-stone-500">Loading…</div>;
  if (!runs.length) return <div className="text-sm text-stone-500">Never run.</div>;
  return (
    <Table head={["Started", "Status", "Queries", "Found", "Imported", "Failed queries"]}>
      {runs.map((r) => (
        <tr key={r.id}>
          <Td className="whitespace-nowrap text-xs text-stone-600">{when(r.started_at)}</Td>
          <Td><Badge>{r.status}</Badge></Td>
          <Td className="tabular-nums">{r.progress.queries_done ?? 0}/{r.progress.queries_planned ?? 0}</Td>
          <Td className="tabular-nums">{r.progress.found ?? 0}</Td>
          <Td className="tabular-nums">{r.created_count} new · {r.duplicate_count} dup</Td>
          <Td className="tabular-nums">{r.progress.warnings?.length ?? 0}</Td>
        </tr>
      ))}
    </Table>
  );
}

export default function DiscoveryPage() {
  const user = useUser();
  const canEdit = user.role !== "readonly";
  const [campaigns, setCampaigns] = useState<DiscoveryCampaign[] | null>(null);
  const [sources, setSources] = useState<DiscoverySourceInfo[]>([]);
  const [tiers, setTiers] = useState<EnrichmentTierInfo[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [history, setHistory] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => api<DiscoveryCampaign[]>("/discovery/campaigns").then(setCampaigns), []);
  useEffect(() => {
    load();
    api<DiscoverySourceInfo[]>("/businesses/discovery-sources").then(setSources);
    api<EnrichmentTierInfo[]>("/businesses/enrichment-tiers").then(setTiers);
  }, [load]);

  const active = campaigns?.find((c) => c.last_run && ACTIVE.has(c.last_run.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 3000); // live progress only while a sweep is queued or running
    return () => clearInterval(timer);
  }, [active, load]);

  async function run(key: string, fn: () => Promise<string>) {
    setBusy(key);
    setNotice(null);
    try {
      setNotice({ tone: "green", text: await fn() });
      await load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    run("save", async () => {
      const body = {
        name: form.name.trim(), description: form.description.trim() || null,
        cities: splitList(form.cities), categories: splitList(form.categories), sources: form.sources,
        enrichment_tiers: form.enrichMode === "all" ? null : form.enrichMode === "none" ? [] : form.tiers,
        target: Number(form.target), per_query: Number(form.perQuery),
      };
      const saved = form.id
        ? await api<DiscoveryCampaign>(`/discovery/campaigns/${form.id}`, { method: "PUT", body })
        : await api<DiscoveryCampaign>("/discovery/campaigns", { body });
      setForm(null);
      return `Saved “${saved.name}”.`;
    });
  };

  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const planned = form ? splitList(form.cities).length * splitList(form.categories).length * form.sources.length : 0;
  const groups = Object.entries(
    sources.reduce<Record<string, DiscoverySourceInfo[]>>((acc, s) => ({ ...acc, [s.category]: [...(acc[s.category] ?? []), s] }), {}),
  );

  return (
    <>
      <PageHeader
        title="Discovery"
        description="Saved sweeps that find businesses across cities and categories. One sweep runs at a time; results land in Businesses."
        actions={canEdit && <Button onClick={() => setForm(form ? null : EMPTY)}>{form ? "Close" : "New campaign"}</Button>}
      />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}

      {active?.last_run && (
        <Card title={<>Sweeping: {active.name}</>} className="mb-6">
          <RunProgress run={active.last_run} busy={busy === "cancel"}
            onCancel={canEdit ? () => run("cancel", async () => {
              await api(`/discovery/runs/${active.last_run!.id}/cancel`, { body: {} });
              return "Stopping after the current query. What was found so far will still be imported.";
            }) : undefined} />
        </Card>
      )}

      {form && (
        <Card title={form.id ? "Edit campaign" : "New campaign"} className="mb-6">
          <form onSubmit={save} className="grid items-start gap-5 lg:grid-cols-2">
            <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Description" hint="Optional: who it is for, how often to run it.">
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Field label="Cities" hint="One per line, or comma-separated.">
              <Textarea rows={4} required value={form.cities} placeholder={"Cebu City\nAngeles City"}
                onChange={(e) => setForm({ ...form, cities: e.target.value })} />
            </Field>
            <Field label="Categories" hint="One per line, e.g. dental clinic, bakery, plumbing.">
              <Textarea rows={4} required value={form.categories} placeholder={"dental clinic\nbakery"}
                onChange={(e) => setForm({ ...form, categories: e.target.value })} />
            </Field>

            <fieldset className="space-y-3">
              <legend className="mb-1 text-sm font-medium">Discovery sources</legend>
              {groups.map(([category, items]) => (
                <div key={category}>
                  <div className="text-xs font-medium uppercase tracking-wide text-stone-500">{CATEGORY_LABEL[category] ?? category}</div>
                  {items.map((s) => (
                    <label key={s.id} className={cx("mt-1.5 flex items-start gap-2 text-sm", !s.configured && "opacity-50")}>
                      <input type="checkbox" className="mt-0.5 accent-brand-600" disabled={!s.configured}
                        checked={form.sources.includes(s.id)} onChange={() => setForm({ ...form, sources: toggle(form.sources, s.id) })} />
                      <span>
                        <span className="font-medium">{s.name}</span>
                        {s.billed && <Badge tone="amber">billed</Badge>}
                        {!s.configured && <Badge tone="gray">not configured</Badge>}
                        {s.note && <span className="block text-xs text-stone-500">{s.note}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            </fieldset>

            <fieldset className="space-y-2">
              <legend className="mb-1 text-sm font-medium">Contact enrichment for new businesses</legend>
              {(["all", "custom", "none"] as EnrichMode[]).map((mode) => (
                <label key={mode} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="enrich" className="accent-brand-600" checked={form.enrichMode === mode}
                    onChange={() => setForm({ ...form, enrichMode: mode })} />
                  {mode === "all" ? "Every enabled tier" : mode === "custom" ? "Only these tiers:" : "No enrichment"}
                </label>
              ))}
              {form.enrichMode === "custom" && (
                <div className="ml-6 space-y-1.5">
                  {tiers.map((t) => (
                    <label key={t.id} className={cx("flex items-start gap-2 text-sm", !t.enabled && "opacity-50")}>
                      <input type="checkbox" className="mt-0.5 accent-brand-600" disabled={!t.enabled}
                        checked={form.tiers.includes(t.id)} onChange={() => setForm({ ...form, tiers: toggle(form.tiers, t.id) })} />
                      <span><span className="font-medium">{t.name}</span> {t.billed && <Badge tone="amber">billed</Badge>}
                        <span className="block text-xs text-stone-500">{t.note}</span></span>
                    </label>
                  ))}
                </div>
              )}
            </fieldset>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Stop after" hint="Unique businesses found.">
                <Input type="number" min={1} max={5000} required value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} />
              </Field>
              <Field label="Results per query">
                <Input type="number" min={1} max={500} required value={form.perQuery} onChange={(e) => setForm({ ...form, perQuery: e.target.value })} />
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
              <Button type="submit" busy={busy === "save"} disabled={!form.sources.length}>Save campaign</Button>
              <span className="text-sm text-stone-500">
                {planned} quer{planned === 1 ? "y" : "ies"} per run
                {form.sources.includes("osm") && planned > 1 && " · OpenStreetMap takes up to a minute per query"}
              </span>
            </div>
          </form>
        </Card>
      )}

      <Card>
        {campaigns && campaigns.length === 0 ? (
          <Empty>No campaigns yet. Create one to sweep cities and categories for businesses.</Empty>
        ) : (
          <Table head={["Campaign", "Sources", "Last run", ""]}>
            {campaigns?.map((c) => (
              <Fragment key={c.id}>
                <tr>
                  <Td>
                    <div className="font-medium">{c.name}</div>
                    <div className="max-w-md truncate text-xs text-stone-500" title={`${c.cities.join(", ")} × ${c.categories.join(", ")}`}>
                      {c.cities.join(", ")} × {c.categories.join(", ")} · stop at {c.target}
                    </div>
                  </Td>
                  <Td><div className="flex flex-wrap gap-1">{c.sources.map((s) => <Badge key={s} tone="blue">{s}</Badge>)}</div></Td>
                  <Td className="text-xs text-stone-600">
                    {c.last_run ? (
                      <div className="flex flex-col gap-1">
                        <span className="flex items-center gap-2"><Badge>{c.last_run.status}</Badge>{when(c.last_run.started_at)}</span>
                        <span>{c.last_run.progress.found ?? 0} found · {c.last_run.created_count} new</span>
                      </div>
                    ) : "Never run"}
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-2">
                      {canEdit && (
                        <Button size="sm" busy={busy === `run-${c.id}`} disabled={Boolean(active)}
                          title={active ? "Another sweep is running" : undefined}
                          onClick={() => run(`run-${c.id}`, async () => {
                            await api(`/discovery/campaigns/${c.id}/run`, { body: {} });
                            return `Started “${c.name}”. Progress updates below every few seconds.`;
                          })}>Run</Button>
                      )}
                      <Button size="sm" variant="secondary" onClick={() => setHistory(history === c.id ? null : c.id)}>
                        {history === c.id ? "Hide runs" : "Runs"}
                      </Button>
                      {canEdit && <Button size="sm" variant="secondary" onClick={() => setForm(toForm(c))}>Edit</Button>}
                      {user.role === "admin" && (
                        <Button size="sm" variant="danger" busy={busy === `del-${c.id}`}
                          onClick={() => window.confirm(`Delete “${c.name}”? Past runs are kept.`) && run(`del-${c.id}`, async () => {
                            await api(`/discovery/campaigns/${c.id}`, { method: "DELETE" });
                            return `Deleted “${c.name}”.`;
                          })}>Delete</Button>
                      )}
                    </div>
                  </Td>
                </tr>
                {history === c.id && (
                  <tr><td colSpan={4} className="bg-stone-50 px-3 py-4"><History campaignId={c.id} /></td></tr>
                )}
              </Fragment>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
