"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Select, Table, Td, Textarea, cx } from "@/components/ui";
import { API_URL, ApiError, api, money, tokens } from "@/lib/api";
import type { Contact, ContactDetail, Page, PipelineStage, Stage } from "@/lib/types";

const STAGES: Stage[] = ["new", "contacted", "qualified", "won", "lost"];
const TEMP_TONE: Record<string, "red" | "amber" | "gray" | "green"> = { hot: "red", warm: "amber", cold: "gray", customer: "green", closed: "gray" };

function ScoreBadge({ contact }: { contact: Contact }) {
  if (contact.lead_score == null || !contact.lead_temperature) return null;
  return <Badge tone={TEMP_TONE[contact.lead_temperature] ?? "gray"}>{contact.lead_temperature} · {contact.lead_score}</Badge>;
}
const STAGE_TONE: Record<Stage, "gray" | "blue" | "amber" | "green" | "red"> = {
  new: "blue", contacted: "amber", qualified: "amber", won: "green", lost: "gray",
};
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

function ContactPanel({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [contact, setContact] = useState<ContactDetail | null>(null);
  const [note, setNote] = useState("");
  const [type, setType] = useState("note");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<ContactDetail>(`/customer/crm/contacts/${id}`).then(setContact);
  }, [id]);
  useEffect(load, [load]);

  if (!contact) return null;
  async function patch(body: Record<string, unknown>) {
    try {
      await api(`/customer/crm/contacts/${id}`, { method: "PATCH", body });
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  return (
    <Card title={contact.name} actions={<Badge tone={STAGE_TONE[contact.stage]}>{contact.stage}</Badge>}>
      <div className="grid gap-4">
        <div className="text-sm text-stone-600">{[contact.email, contact.phone && `+${contact.phone}`].filter(Boolean).join(" · ") || "No contact details"}</div>
        {contact.lead_score != null && (
          <div className="rounded-lg bg-stone-50 p-3 text-sm">
            <div className="mb-1 flex items-center gap-2 font-medium">Lead score <ScoreBadge contact={contact} /></div>
            <ul className="list-disc pl-5 text-xs text-stone-600">{contact.score_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="flex flex-wrap gap-1.5">
          {STAGES.map((s) => (
            <button key={s} onClick={() => patch({ stage: s })} className={cx(
              "rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
              contact.stage === s ? "bg-brand-600 text-white ring-brand-600" : "text-stone-600 ring-line hover:bg-stone-50",
            )}>{s}</button>
          ))}
        </div>
        <Field label="Deal value (PHP)">
          <Input type="number" min={0} defaultValue={contact.value_cents ? contact.value_cents / 100 : ""}
            onBlur={(e) => patch({ value_cents: e.target.value ? Math.round(Number(e.target.value) * 100) : null })} />
        </Field>
        <form className="grid gap-2" onSubmit={async (e) => {
          e.preventDefault();
          if (!note.trim()) return;
          await api(`/customer/crm/contacts/${id}/activities`, { body: { type, body: note } });
          setNote("");
          load();
          onChanged();
        }}>
          <div className="flex gap-2">
            <Select value={type} onChange={(e) => setType(e.target.value)} className="w-32">
              {["note", "call", "email", "meeting"].map((t) => <option key={t}>{t}</option>)}
            </Select>
            <Button type="submit" variant="secondary">Log</Button>
          </div>
          <Textarea rows={2} placeholder="What happened?" value={note} onChange={(e) => setNote(e.target.value)} />
        </form>
        <ol className="grid gap-3 border-l border-line pl-4">
          {contact.activities.map((a) => (
            <li key={a.id} className="text-sm">
              <div className="flex justify-between gap-3 text-xs text-stone-500">
                <span className="font-medium uppercase tracking-wide">{a.type.replaceAll("_", " ")}</span>
                <span>{when(a.occurred_at)}</span>
              </div>
              {a.body && <p className="mt-0.5 whitespace-pre-wrap">{a.body}</p>}
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}

function Leads() {
  const [data, setData] = useState<Page<Contact> | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
  const [filter, setFilter] = useState<{ q: string; stage: string }>({ q: "", stage: "" });
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "" });
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams({ page_size: "100" });
    if (filter.q) params.set("q", filter.q);
    if (filter.stage) params.set("stage", filter.stage);
    api<Page<Contact>>(`/customer/crm/contacts?${params}`).then(setData);
    api<PipelineStage[]>("/customer/crm/pipeline").then(setPipeline);
  }, [filter]);
  useEffect(load, [load]);

  async function exportCsv() {
    const res = await fetch(`${API_URL}/api/v1/customer/crm/export.csv`, { headers: { Authorization: `Bearer ${tokens.access}` } });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "contacts.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <PageHeader title="Leads & CRM" description="Everyone who contacted you through your website, bookings or chat."
        actions={<>
          <Button variant="secondary" onClick={exportCsv}>Export CSV</Button>
          <Button onClick={() => setAdding((v) => !v)}>{adding ? "Close" : "Add contact"}</Button>
        </>} />
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {pipeline.map((p) => (
          <button key={p.stage} onClick={() => setFilter({ ...filter, stage: filter.stage === p.stage ? "" : p.stage })}
            className={cx("rounded-xl border bg-white p-3 text-left", filter.stage === p.stage ? "border-brand-600 ring-1 ring-brand-600" : "border-line")}>
            <div className="text-xs font-medium uppercase tracking-wide text-stone-500">{p.stage}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums">{p.count}</div>
            {p.value_cents > 0 && <div className="text-xs tabular-nums text-stone-500">{money(p.value_cents)}</div>}
          </button>
        ))}
      </div>
      {adding && (
        <Card className="mb-6" title="New contact">
          <form className="grid gap-3 sm:grid-cols-4 sm:items-end" onSubmit={async (e) => {
            e.preventDefault();
            setError("");
            try {
              await api("/customer/crm/contacts", { body: { name: form.name, email: form.email || null, phone: form.phone || null } });
              setForm({ name: "", email: "", phone: "" });
              setAdding(false);
              load();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not add contact");
            }
          }}>
            <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Phone"><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Button type="submit">Save</Button>
            {error && <div className="sm:col-span-4"><Alert>{error}</Alert></div>}
          </form>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <Card>
          <Input placeholder="Search name, email or phone" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} className="mb-4 w-72" />
          {data && data.items.length === 0 ? (
            <Empty>No contacts yet. Inquiries from your website will appear here automatically.</Empty>
          ) : (
            <Table head={["Contact", "Score", "Source", "Stage", "Last activity"]}>
              {data?.items.map((c) => (
                <tr key={c.id} onClick={() => setSelected(c.id)} className={cx("cursor-pointer hover:bg-stone-50", selected === c.id && "bg-brand-50")}>
                  <Td><div className="font-medium">{c.name}</div><div className="text-xs text-stone-500">{c.email ?? (c.phone && `+${c.phone}`)}</div></Td>
                  <Td><ScoreBadge contact={c} /></Td>
                  <Td className="text-xs text-stone-600">{c.source.replaceAll("_", " ")}</Td>
                  <Td><Badge tone={STAGE_TONE[c.stage]}>{c.stage}</Badge></Td>
                  <Td className="whitespace-nowrap text-xs text-stone-500">{when(c.last_activity_at)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <div>{selected ? <ContactPanel id={selected} onChanged={load} /> : <Empty>Select a contact to see its history.</Empty>}</div>
      </div>
    </>
  );
}

export default function LeadsPage() {
  return <FeatureGate feature="crm"><Leads /></FeatureGate>;
}
