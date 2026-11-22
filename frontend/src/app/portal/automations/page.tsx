"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Automation, AutomationRun, Preset } from "@/lib/types";

const TRIGGER_LABEL: Record<string, string> = {
  lead_captured: "When a new lead comes in",
  lead_became_hot: "When a lead becomes hot",
  stage_changed: "When a contact changes stage",
  appointment_booked: "When an appointment is booked",
  appointment_cancelled: "When an appointment is cancelled",
  appointment_reminder: "Before an appointment",
  contact_idle: "When a lead goes quiet",
  call_completed: "After a phone call",
};
const ACTION_LABEL: Record<string, string> = {
  email_contact: "Email the customer", sms_contact: "Text the customer", notify_owner: "Email me",
  set_stage: "Move to stage", add_tag: "Add tag",
};

function describe(a: Automation | Preset) {
  const when = TRIGGER_LABEL[a.trigger] ?? a.trigger;
  const timing = a.config.hours_before ? ` (${a.config.hours_before} h before)` : a.config.idle_days ? ` (${a.config.idle_days} days)` : "";
  return `${when}${timing}`;
}

function Automations() {
  const [rules, setRules] = useState<Automation[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<Automation[]>("/customer/automations").then(setRules);
    api<AutomationRun[]>("/customer/automations/runs").then(setRuns);
  }, []);
  useEffect(() => {
    load();
    api<Preset[]>("/customer/automations/presets").then(setPresets);
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    }
  }

  const installed = new Set(rules.map((r) => r.preset_key).filter(Boolean));
  const ruleName = Object.fromEntries(rules.map((r) => [r.id, r.name]));

  return (
    <>
      <PageHeader title="Automations" description="Let GumaWeb follow up for you: thank new leads, send reminders, and flag hot leads." />
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      <div className="grid gap-6">
        <Card title="Recommended">
          <div className="grid gap-3 sm:grid-cols-2">
            {presets.map((p) => (
              <div key={p.key} className="flex items-start justify-between gap-3 rounded-lg border border-line p-4">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="mt-0.5 text-sm text-stone-600">{describe(p)} → {p.actions.map((a) => ACTION_LABEL[a.type]).join(", ")}</div>
                </div>
                {installed.has(p.key) ? <Badge tone="green">on</Badge> : (
                  <Button size="sm" variant="secondary" onClick={() => run(() => api(`/customer/automations/presets/${p.key}`, { body: {} }))}>Turn on</Button>
                )}
              </div>
            ))}
          </div>
        </Card>
        <Card title="Your automations">
          {rules.length === 0 ? <Empty>Turn on a recommended automation to get started.</Empty> : (
            <ul className="divide-y divide-line">
              {rules.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div>
                    <div className="font-medium">{r.name}</div>
                    <div className="text-sm text-stone-600">{describe(r)} → {r.actions.map((a) => ACTION_LABEL[a.type] + (a.stage ? `: ${a.stage}` : a.tag ? `: ${a.tag}` : "")).join(", ")}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="accent-brand-600" checked={r.enabled}
                        onChange={(e) => run(() => api(`/customer/automations/${r.id}`, { method: "PATCH", body: { enabled: e.target.checked } }))} />
                      {r.enabled ? "On" : "Off"}
                    </label>
                    <button className="text-xs text-red-700 hover:underline" onClick={() => run(() => api(`/customer/automations/${r.id}`, { method: "DELETE" }))}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recent activity">
          {runs.length === 0 ? <Empty>Automation runs will appear here.</Empty> : (
            <ul className="divide-y divide-line text-sm">
              {runs.slice(0, 20).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
                  <span>{ruleName[r.rule_id] ?? "Automation"} · <span className="text-stone-500">{r.results.map((x) => `${ACTION_LABEL[x.type] ?? x.type}: ${x.status}`).join(", ")}</span></span>
                  <span className="flex items-center gap-2 whitespace-nowrap text-xs text-stone-500">
                    <Badge tone={r.status === "succeeded" ? "green" : r.status === "failed" ? "red" : "gray"}>{r.status}</Badge>
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

export default function AutomationsPage() {
  return <FeatureGate feature="automation"><Automations /></FeatureGate>;
}
