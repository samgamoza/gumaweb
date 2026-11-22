"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Table, Td } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Campaign, CampaignStats } from "@/lib/types";

export default function OutreachPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [stats, setStats] = useState<Record<string, CampaignStats>>({});
  const [form, setForm] = useState({ name: "", industry: "", city: "", min_score: "" });
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const list = await api<Campaign[]>("/outreach/campaigns");
    setCampaigns(list);
    const entries = await Promise.all(list.map(async (c) => [c.id, await api<CampaignStats>(`/outreach/campaigns/${c.id}/stats`)] as const));
    setStats(Object.fromEntries(entries));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function run(key: string, fn: () => Promise<string>) {
    setBusy(key);
    try {
      setNotice({ tone: "green", text: await fn() });
      await load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    run("create", async () => {
      const target_filter = {
        ...(form.industry && { industry: form.industry }),
        ...(form.city && { city: form.city }),
        ...(form.min_score && { min_score: Number(form.min_score) }),
      };
      const r = await api<{ enrolled_businesses: number; scheduled_messages: number }>("/outreach/campaign", {
        body: { name: form.name, target_filter },
      });
      setForm({ name: "", industry: "", city: "", min_score: "" });
      return `Campaign launched: ${r.enrolled_businesses} businesses enrolled, ${r.scheduled_messages} messages scheduled (Day 0/3/7/14).`;
    });
  };

  return (
    <>
      <PageHeader title="Outreach" description="Tell businesses we built their website. Unclaimed, published sites with an email are eligible." />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
      <Card title="New campaign" className="mb-6">
        <form onSubmit={create} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
          <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Industry"><Input placeholder="any" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></Field>
          <Field label="City"><Input placeholder="any" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></Field>
          <Field label="Min. score"><Input type="number" min={0} max={100} value={form.min_score} onChange={(e) => setForm({ ...form, min_score: e.target.value })} /></Field>
          <Button type="submit" busy={busy === "create"}>Launch campaign</Button>
        </form>
      </Card>
      <Card title="Campaigns">
        {campaigns.length === 0 ? (
          <Empty>No campaigns yet.</Empty>
        ) : (
          <Table head={["Campaign", "Status", "Sent", "Opened", "Clicked", "Claims", "Converted", ""]}>
            {campaigns.map((c) => {
              const s = stats[c.id];
              return (
                <tr key={c.id}>
                  <Td>
                    <div className="font-medium">{c.name}</div>
                    <div className="text-xs text-stone-500">{Object.entries(c.target_filter).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>
                  </Td>
                  <Td><Badge>{c.status}</Badge></Td>
                  {(["outreach_sent", "opens", "clicks", "claims", "conversions"] as const).map((key) => (
                    <Td key={key} className="tabular-nums">{s?.[key] ?? "—"}</Td>
                  ))}
                  <Td className="text-right">
                    {c.status === "active" && (
                      <Button size="sm" variant="secondary" busy={busy === c.id} onClick={() => run(c.id, async () => {
                        const r = await api<{ sent: number; skipped: number; failed: number }>(`/outreach/campaigns/${c.id}/dispatch`, { body: {} });
                        return `Dispatched: ${r.sent} sent, ${r.skipped} skipped, ${r.failed} failed.`;
                      })}>Send due now</Button>
                    )}
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </>
  );
}
