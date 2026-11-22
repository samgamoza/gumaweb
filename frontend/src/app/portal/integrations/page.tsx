"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Table, Td } from "@/components/ui";
import { API_URL, ApiError, api } from "@/lib/api";
import type { ApiKey, Delivery, Webhook } from "@/lib/types";

const EVENTS = ["lead.captured", "lead.hot", "contact.stage_changed", "appointment.booked", "appointment.cancelled", "call.completed"];

function ApiKeys() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [readOnly, setReadOnly] = useState(true);
  const [created, setCreated] = useState<string | null>(null);
  const load = useCallback(() => { api<ApiKey[]>("/customer/integrations/api-keys").then(setKeys); }, []);
  useEffect(load, [load]);
  return (
    <Card title="API keys">
      <p className="mb-4 text-sm text-stone-600">
        Let other systems (like Guma One) read your leads, bookings and calls. Use the key as a Bearer token with the
        GumaWeb API at <code className="rounded bg-stone-100 px-1">{API_URL}/api/v1/customer/…</code>.
      </p>
      {created && (
        <div className="mb-4"><Alert tone="amber">Copy this key now. It won&apos;t be shown again:<br /><code className="break-all font-mono text-xs">{created}</code></Alert></div>
      )}
      <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={async (e) => {
        e.preventDefault();
        const k = await api<ApiKey>("/customer/integrations/api-keys", { body: { name, read_only: readOnly } });
        setCreated(k.key ?? null);
        setName("");
        load();
      }}>
        <Field label="Name"><Input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Guma One sync" className="w-60" /></Field>
        <label className="flex h-10 items-center gap-2 text-sm"><input type="checkbox" className="accent-brand-600" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} />Read-only</label>
        <Button type="submit">Create key</Button>
      </form>
      {keys.length === 0 ? <Empty>No API keys yet.</Empty> : (
        <Table head={["Name", "Key", "Access", "Last used", ""]}>
          {keys.map((k) => (
            <tr key={k.id}>
              <Td className="font-medium">{k.name}</Td>
              <Td className="font-mono text-xs">{k.prefix}…</Td>
              <Td><Badge tone={k.read_only ? "gray" : "amber"}>{k.read_only ? "read-only" : "read & write"}</Badge></Td>
              <Td className="text-xs text-stone-500">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "Never"}</Td>
              <Td className="text-right"><Button size="sm" variant="danger" onClick={async () => { await api(`/customer/integrations/api-keys/${k.id}`, { method: "DELETE" }); load(); }}>Revoke</Button></Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function Webhooks() {
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["lead.captured"]);
  const [secret, setSecret] = useState<{ id: string; value: string } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<Webhook[]>("/customer/integrations/webhooks").then(setHooks);
    api<Delivery[]>("/customer/integrations/deliveries").then(setDeliveries);
  }, []);
  useEffect(load, [load]);

  return (
    <Card title="Webhooks">
      <p className="mb-4 text-sm text-stone-600">
        GumaWeb sends a signed <code className="rounded bg-stone-100 px-1">POST</code> to your URL when these events happen.
        Verify the <code className="rounded bg-stone-100 px-1">GumaWeb-Signature</code> header (HMAC-SHA256 of <code>timestamp.body</code>) with the endpoint secret.
      </p>
      {error && <div className="mb-3"><Alert>{error}</Alert></div>}
      <form className="mb-5 grid gap-3" onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        try {
          await api("/customer/integrations/webhooks", { body: { url, events } });
          setUrl("");
          load();
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Could not add webhook");
        }
      }}>
        <Field label="Endpoint URL"><Input required type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hooks/gumaweb" /></Field>
        <div className="flex flex-wrap gap-3 text-sm">
          {EVENTS.map((ev) => (
            <label key={ev} className="flex items-center gap-1.5">
              <input type="checkbox" className="accent-brand-600" checked={events.includes(ev)}
                onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))} />
              <code className="text-xs">{ev}</code>
            </label>
          ))}
        </div>
        <div><Button type="submit" disabled={!events.length}>Add webhook</Button></div>
      </form>
      {hooks.length === 0 ? <Empty>No webhooks yet.</Empty> : (
        <ul className="grid gap-3">
          {hooks.map((h) => (
            <li key={h.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{h.url}</div>
                  <div className="text-xs text-stone-500">{h.events.join(", ")}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={h.active ? "green" : "red"}>{h.active ? "active" : "disabled"}</Badge>
                  <Button size="sm" variant="secondary" onClick={async () => { await api(`/customer/integrations/webhooks/${h.id}/test`, { body: {} }); setTimeout(load, 1500); }}>Send test</Button>
                  <Button size="sm" variant="ghost" onClick={async () => setSecret({ id: h.id, value: (await api<{ secret: string }>(`/customer/integrations/webhooks/${h.id}/secret`)).secret })}>Show secret</Button>
                  {!h.active && <Button size="sm" variant="ghost" onClick={async () => { await api(`/customer/integrations/webhooks/${h.id}`, { method: "PATCH", body: { active: true } }); load(); }}>Re-enable</Button>}
                  <button className="text-xs text-red-700 hover:underline" onClick={async () => { await api(`/customer/integrations/webhooks/${h.id}`, { method: "DELETE" }); load(); }}>Delete</button>
                </div>
              </div>
              {secret?.id === h.id && <code className="mt-2 block break-all rounded bg-stone-100 p-2 font-mono text-xs">{secret.value}</code>}
            </li>
          ))}
        </ul>
      )}
      {deliveries.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 text-sm font-medium">Recent deliveries</div>
          <Table head={["Event", "Status", "HTTP", "Attempts", "When"]}>
            {deliveries.slice(0, 15).map((d) => (
              <tr key={d.id}>
                <Td className="font-mono text-xs">{d.event_type}</Td>
                <Td><Badge tone={d.status === "delivered" ? "green" : d.status === "failed" ? "red" : "gray"}>{d.status}</Badge></Td>
                <Td className="tabular-nums text-xs">{d.response_status ?? "—"}</Td>
                <Td className="tabular-nums text-xs">{d.attempts}</Td>
                <Td className="text-xs text-stone-500" >{new Date(d.created_at).toLocaleString()}</Td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </Card>
  );
}

export default function IntegrationsPage() {
  return (
    <FeatureGate feature="integrations">
      <PageHeader title="Integrations" description="Connect GumaWeb to Guma One and your other tools." />
      <div className="grid gap-6">
        <ApiKeys />
        <Webhooks />
      </div>
    </FeatureGate>
  );
}
