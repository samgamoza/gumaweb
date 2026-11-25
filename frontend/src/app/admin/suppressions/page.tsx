"use client";

import { useCallback, useEffect, useState } from "react";
import { useUser } from "@/components/auth-guard";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Select, Table, Td } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Suppression } from "@/lib/types";

const REASONS = [
  { value: "requested", label: "Asked not to be contacted" },
  { value: "unsubscribed", label: "Unsubscribed" },
  { value: "bounced", label: "Hard bounce" },
  { value: "complaint", label: "Spam complaint" },
  { value: "legal", label: "Legal / regulator request" },
];

const EMPTY = { kind: "email" as "email" | "domain", value: "", reason: "requested", note: "" };

interface CheckResult { email: string; suppressed: boolean; matched_kind: string | null; matched_value: string | null }

export default function SuppressionsPage() {
  const user = useUser();
  const [items, setItems] = useState<Suppression[] | null>(null);
  const [filter, setFilter] = useState<"" | "email" | "domain">("");
  const [form, setForm] = useState(EMPTY);
  const [check, setCheck] = useState("");
  const [checked, setChecked] = useState<CheckResult | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => api<Suppression[]>(`/outreach/suppressions${filter ? `?kind=${filter}` : ""}`).then(setItems), [filter]);
  useEffect(() => { load(); }, [load]);

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

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    run("add", async () => {
      const entry = await api<Suppression>("/outreach/suppressions", {
        body: { kind: form.kind, value: form.value.trim(), reason: form.reason, note: form.note.trim() || null },
      });
      setForm(EMPTY);
      return entry.kind === "domain"
        ? `Every address at ${entry.value} is now blocked from outreach and enrichment.`
        : `${entry.value} is now blocked from outreach.`;
    });
  };

  const runCheck = (e: React.FormEvent) => {
    e.preventDefault();
    setChecked(null);
    api<CheckResult>(`/outreach/suppressions/check?email=${encodeURIComponent(check.trim())}`)
      .then(setChecked)
      .catch((err) => setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Check failed" }));
  };

  return (
    <>
      <PageHeader
        title="Do-not-contact"
        description="Addresses and whole domains that outreach and contact enrichment must never use. Unsubscribes land here automatically."
      />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}

      <div className="mb-6 grid gap-6 lg:grid-cols-[2fr_1fr]">
        {user.role !== "readonly" && (
          <Card title="Add an entry">
            <form onSubmit={add} className="grid items-start gap-4 sm:grid-cols-2">
              <Field label="Type">
                <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as "email" | "domain" })}>
                  <option value="email">One email address</option>
                  <option value="domain">A whole domain</option>
                </Select>
              </Field>
              <Field label={form.kind === "domain" ? "Domain" : "Email"} hint={form.kind === "domain" ? "e.g. acme.ph — blocks exactly this domain, not its subdomains." : undefined}>
                <Input required value={form.value} placeholder={form.kind === "domain" ? "acme.ph" : "owner@acme.ph"}
                  onChange={(e) => setForm({ ...form, value: e.target.value })} />
              </Field>
              <Field label="Reason">
                <Select value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })}>
                  {REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </Select>
              </Field>
              <Field label="Note" hint="Optional: ticket number, who asked, how.">
                <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
              </Field>
              <div className="sm:col-span-2"><Button type="submit" busy={busy === "add"}>Block</Button></div>
            </form>
          </Card>
        )}
        <Card title="Is this address blocked?">
          <form onSubmit={runCheck} className="flex gap-2">
            <Input required type="email" value={check} placeholder="someone@shop.ph" onChange={(e) => setCheck(e.target.value)} />
            <Button type="submit" variant="secondary">Check</Button>
          </form>
          {checked && (
            <div className="mt-3 text-sm">
              {checked.suppressed
                ? <Alert tone="amber">Blocked by the {checked.matched_kind} entry <strong>{checked.matched_value}</strong>.</Alert>
                : <Alert tone="green">Not blocked. Outreach may contact {checked.email}.</Alert>}
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Entries"
        actions={
          <Select value={filter} className="w-36" onChange={(e) => setFilter(e.target.value as "" | "email" | "domain")}>
            <option value="">All</option>
            <option value="email">Emails</option>
            <option value="domain">Domains</option>
          </Select>
        }
      >
        {items && items.length === 0 ? <Empty>Nothing is blocked yet.</Empty> : (
          <Table head={["Entry", "Type", "Reason", "Note", "Added", ""]}>
            {items?.map((s) => (
              <tr key={s.id}>
                <Td className="font-medium">{s.value}</Td>
                <Td><Badge tone={s.kind === "domain" ? "blue" : "gray"}>{s.kind}</Badge></Td>
                <Td className="text-stone-600">{REASONS.find((r) => r.value === s.reason)?.label ?? s.reason}</Td>
                <Td className="max-w-64 truncate text-xs text-stone-600" >{s.note ?? "—"}</Td>
                <Td className="whitespace-nowrap text-xs text-stone-500">{new Date(s.created_at).toLocaleDateString()}</Td>
                <Td className="text-right">
                  {user.role === "admin" && (
                    <Button size="sm" variant="danger" busy={busy === s.id}
                      onClick={() => window.confirm(`Allow contact with ${s.value} again?`) && run(s.id, async () => {
                        await api(`/outreach/suppressions/${s.kind}/${encodeURIComponent(s.value)}`, { method: "DELETE" });
                        return `${s.value} removed. Anyone who unsubscribed personally stays blocked.`;
                      })}>Remove</Button>
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
