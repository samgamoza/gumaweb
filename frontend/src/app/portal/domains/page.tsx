"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { CustomDomainRow, DnsRecordRow } from "@/lib/types";

const STATUS_TONE = { pending: "amber", verified: "green", failed: "red" } as const;

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="text-xs font-medium text-brand-700 hover:underline" onClick={async () => {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    }}>{done ? "Copied" : "Copy"}</button>
  );
}

function Records({ records, title }: { records: DnsRecordRow[]; title: string }) {
  if (!records.length) return null;
  return (
    <div className="grid gap-2">
      <div className="text-sm font-medium">{title}</div>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-stone-50 text-stone-500">
            <tr><th className="px-3 py-2">Type</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Value</th><th className="px-3 py-2">What it does</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {records.map((r) => (
              <tr key={`${r.type}-${r.name}-${r.value}`} className={cx(r.required === false && "text-stone-500")}>
                <td className="px-3 py-2 font-mono">{r.type}</td>
                <td className="px-3 py-2 font-mono"><span className="break-all">{r.name}</span> <Copy text={r.name} /></td>
                <td className="px-3 py-2 font-mono"><span className="break-all">{r.priority != null ? `${r.priority} ` : ""}{r.value}</span> <Copy text={r.value} /></td>
                <td className="px-3 py-2">{r.purpose}{r.required === false && " (optional)"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Email({ d, run }: { d: CustomDomainRow; run: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [local, setLocal] = useState("");
  const [kind, setKind] = useState<"mailbox" | "forward">("mailbox");
  const [forward, setForward] = useState("");
  const [secret, setSecret] = useState<{ address: string; password: string } | null>(null);
  const base = `/customer/domains/${d.id}`;
  if (d.status !== "verified") return <p className="text-sm text-stone-500">Verify the domain to set up email.</p>;
  if (!d.email) {
    return <div><Button variant="secondary" onClick={() => run(() => api(`${base}/email`, { body: {} }))}>Set up email on {d.domain}</Button></div>;
  }
  const mailRecords = d.records.filter((r) => r.required !== undefined);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Email</span>
        <Badge tone={d.email.status === "active" ? "green" : d.email.status === "suspended" ? "red" : "amber"}>
          {d.email.status === "dns_pending" ? "waiting for DNS" : d.email.status}
        </Badge>
        <Button size="sm" variant="ghost" onClick={() => run(() => api(`${base}/email/check`, { body: {} }))}>Check DNS records</Button>
      </div>
      {d.email.status === "suspended" && <Alert tone="amber">Your plan no longer includes email. Existing mailboxes keep working; upgrade to add new addresses.</Alert>}
      {d.email.dns_missing.length > 0 && <Alert tone="amber">Not found in DNS yet: {d.email.dns_missing.join(", ")}. Changes can take a few hours to appear.</Alert>}
      <Records records={mailRecords} title="Email DNS records (add them where you bought the domain)" />
      {secret && (
        <Alert tone="green">
          <strong>{secret.address}</strong> password (copy it now, it won&apos;t be shown again): <code className="font-mono">{secret.password}</code> <Copy text={secret.password} />
        </Alert>
      )}
      {d.email.addresses.length === 0 ? <Empty>No email addresses yet.</Empty> : (
        <ul className="divide-y divide-line rounded-lg border border-line text-sm">
          {d.email.addresses.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span><span className="font-medium">{a.address}</span> {a.kind === "forward" ? <span className="text-stone-500">→ {a.forward_to.join(", ")}</span> : a.display_name && <span className="text-stone-500">{a.display_name}</span>}</span>
              <span className="flex gap-3">
                {a.kind === "mailbox" && <button className="text-xs font-medium text-brand-700 hover:underline" onClick={() => run(async () => setSecret(await api(`${base}/mailboxes/${a.id}/reset-password`, { body: {} })))}>New password</button>}
                <button className="text-xs text-red-700 hover:underline" onClick={() => run(() => api(`${base}/mailboxes/${a.id}`, { method: "DELETE" }))}>Delete</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
        e.preventDefault();
        run(async () => {
          const created = await api<{ address: string; password?: string }>(`${base}/mailboxes`, {
            body: { local_part: local, kind, forward_to: kind === "forward" ? forward.split(/[\s,]+/).filter(Boolean) : [] },
          });
          if (created.password) setSecret({ address: created.address, password: created.password });
          setLocal("");
          setForward("");
        });
      }}>
        <Field label="New address"><div className="flex items-center gap-1"><Input required value={local} onChange={(e) => setLocal(e.target.value)} placeholder="info" className="w-36" /><span className="text-sm text-stone-500">@{d.domain}</span></div></Field>
        <Field label="Type">
          <select className="h-10 rounded-md border border-line bg-white px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value as "mailbox" | "forward")}>
            <option value="mailbox">Mailbox</option><option value="forward">Forward to…</option>
          </select>
        </Field>
        {kind === "forward" && <Field label="Forward to"><Input required value={forward} onChange={(e) => setForward(e.target.value)} placeholder="you@gmail.com" className="w-56" /></Field>}
        <Button type="submit">Add</Button>
      </form>
      <p className="text-xs text-stone-500">Mail apps: incoming {d.email.client_settings.incoming}; outgoing {d.email.client_settings.outgoing}; username is {d.email.client_settings.username}.</p>
    </div>
  );
}

function Domains() {
  const [domains, setDomains] = useState<CustomDomainRow[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => { api<CustomDomainRow[]>("/customer/domains").then(setDomains); }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    }
  }

  return (
    <>
      <PageHeader title="Domain & email" description="Use your own domain for your website and email addresses like info@yourbusiness.ph." />
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      <div className="grid gap-6">
        <Card title="Connect a domain">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/customer/domains", { body: { domain: name } }); setName(""); }); }}>
            <Field label="Your domain"><Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="yourbusiness.ph" className="w-72" /></Field>
            <Button type="submit">Connect</Button>
          </form>
          <p className="mt-3 text-xs text-stone-500">Don&apos;t have one yet? Buy it from any domain registrar, then connect it here.</p>
        </Card>
        {domains.map((d) => {
          const siteRecords = d.records.filter((r) => r.required === undefined);
          return (
            <Card key={d.id} title={d.domain} actions={<Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>}>
              <div className="grid gap-5">
                {d.status !== "verified" && (
                  <>
                    <Records records={siteRecords} title="Add these DNS records where you bought the domain" />
                    {d.last_error && <Alert tone="amber">{d.last_error}</Alert>}
                    <div><Button onClick={() => run(() => api(`/customer/domains/${d.id}/verify`, { body: {} }))}>Check now</Button></div>
                  </>
                )}
                {d.status === "verified" && (
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-brand-600" checked={d.serve_website}
                      onChange={(e) => run(() => api(`/customer/domains/${d.id}/website`, { method: "PUT", body: { serve_website: e.target.checked } }))} />
                    Show my website at <span className="font-medium">{d.domain}</span>
                    {d.serve_website && <a className="text-brand-700 hover:underline" href={`https://${d.domain}`} target="_blank" rel="noreferrer">Open</a>}
                  </label>
                )}
                {d.status === "verified" && <Records records={siteRecords.filter((r) => r.type !== "TXT")} title="Website DNS records" />}
                <Email d={d} run={run} />
                <div><button className="text-xs text-red-700 hover:underline" onClick={() => run(() => api(`/customer/domains/${d.id}`, { method: "DELETE" }))}>Remove domain</button></div>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}

export default function DomainsPage() {
  return <FeatureGate feature="custom_domain"><Domains /></FeatureGate>;
}
