"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, ScoreBar, Select, Table, Td } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Business, DiscoveryRun, Page } from "@/lib/types";

const EMPTY_FORM = { name: "", industry: "", city: "", province: "", phone: "", email: "", facebook: "", website: "" };

export default function BusinessesPage() {
  const [data, setData] = useState<Page<Business> | null>(null);
  const [filters, setFilters] = useState({ q: "", status: "", candidate: false });
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (filters.q) params.set("q", filters.q);
    if (filters.status) params.set("status", filters.status);
    if (filters.candidate) params.set("generate_candidate", "true");
    api<Page<Business>>(`/businesses?${params}`).then(setData);
  }, [filters, page]);
  useEffect(load, [load]);

  async function run(key: string, fn: () => Promise<string>) {
    setBusy(key);
    setNotice(null);
    try {
      setNotice({ tone: "green", text: await fn() });
      load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    run("create", async () => {
      const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]));
      const b = await api<Business>("/businesses", { body });
      setForm(EMPTY_FORM);
      setShowForm(false);
      return `Added ${b.name} (score ${b.score}${b.generate_candidate ? ", generate candidate" : ""}).`;
    });
  };

  const importFile = (file: File) =>
    run("import", async () => {
      const form = new FormData();
      form.append("file", file);
      const r = await api<DiscoveryRun>("/businesses/import", { form });
      if (fileRef.current) fileRef.current.value = "";
      return `Import ${r.status}: ${r.created_count} created, ${r.duplicate_count} duplicates, ${r.error_count} errors.`;
    });

  // Generation can take a while with AI enabled, so it runs on the factory workers, not in this request.
  const generate = (b: Business) =>
    run(b.id, async () => {
      const r = await api<{ enqueued: number }>("/websites/generate-batch", { body: { business_ids: [b.id], publish: true } });
      return r.enqueued ? `Queued ${b.name}. Track it under Factory jobs.` : `${b.name} is already queued.`;
    });

  return (
    <>
      <PageHeader
        title="Businesses"
        description="Discovered businesses, ranked by opportunity score."
        actions={
          <>
            <input ref={fileRef} type="file" accept=".csv,.json" className="hidden" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
            <Button variant="secondary" busy={busy === "import"} onClick={() => fileRef.current?.click()}>Import CSV / JSON</Button>
            <Button onClick={() => setShowForm((v) => !v)}>{showForm ? "Close" : "Add business"}</Button>
          </>
        }
      />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}

      {showForm && (
        <Card title="New business" className="mb-6">
          <form onSubmit={create} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {(Object.keys(EMPTY_FORM) as (keyof typeof EMPTY_FORM)[]).map((key) => (
              <Field key={key} label={key[0].toUpperCase() + key.slice(1)}>
                <Input required={key === "name"} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </Field>
            ))}
            <div className="sm:col-span-2 lg:col-span-4"><Button type="submit" busy={busy === "create"}>Save and score</Button></div>
          </form>
        </Card>
      )}

      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Input placeholder="Search name or city" value={filters.q} className="w-64"
            onChange={(e) => { setPage(1); setFilters({ ...filters, q: e.target.value }); }} />
          <Select value={filters.status} className="w-44" onChange={(e) => { setPage(1); setFilters({ ...filters, status: e.target.value }); }}>
            <option value="">Active statuses</option>
            {["discovered", "scored", "profiled", "generated", "published", "claimed", "archived"].map((s) => <option key={s}>{s}</option>)}
          </Select>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-brand-600" checked={filters.candidate}
              onChange={(e) => { setPage(1); setFilters({ ...filters, candidate: e.target.checked }); }} />
            Generate candidates only
          </label>
        </div>
        {data && data.items.length === 0 ? (
          <Empty>No businesses match. Add one or import a directory export.</Empty>
        ) : (
          <Table head={["Business", "Industry", "Contact", "Score", "Status", ""]}>
            {data?.items.map((b) => (
              <tr key={b.id}>
                <Td>
                  <div className="font-medium">{b.name}</div>
                  <div className="text-xs text-stone-500">{[b.city, b.province].filter(Boolean).join(", ")}</div>
                </Td>
                <Td className="text-stone-600">{b.industry ?? "—"}</Td>
                <Td className="text-xs text-stone-600">
                  <div>{b.phone ? `+${b.phone}` : "—"}</div>
                  <div>{b.email}</div>
                </Td>
                <Td><span title={b.score_breakdown?.reasons?.join("\n")}><ScoreBar value={b.score} /></span></Td>
                <Td>
                  <div className="flex items-center gap-1.5">
                    <Badge>{b.status}</Badge>
                    {b.generate_candidate && <Badge tone="blue">candidate</Badge>}
                  </div>
                </Td>
                <Td className="text-right">
                  {b.generate_candidate && ["scored", "profiled", "discovered"].includes(b.status) && (
                    <Button size="sm" variant="secondary" busy={busy === b.id} onClick={() => generate(b)}>Generate &amp; publish</Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
        {data && data.total > data.page_size && (
          <div className="mt-4 flex items-center justify-between text-sm text-stone-600">
            <span>{data.total} businesses</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button size="sm" variant="secondary" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
