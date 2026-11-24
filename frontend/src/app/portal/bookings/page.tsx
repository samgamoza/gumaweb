"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Select, Table, Td } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Appointment, BookingSettings } from "@/lib/types";

const DAYS: [string, string][] = [["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"],
  ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]];
const STATUS_TONE = { pending: "amber", confirmed: "green", cancelled: "gray", completed: "blue", no_show: "red" } as const;

function SettingsCard({ initial, onSaved }: { initial: BookingSettings; onSaved: (s: BookingSettings) => void }) {
  const [s, setS] = useState(initial);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(next: BookingSettings) {
    setBusy(true);
    setNotice(null);
    try {
      const saved = await api<BookingSettings>("/customer/booking/settings", { method: "PUT", body: next });
      setS(saved);
      onSaved(saved);
      setNotice({ tone: "green", text: saved.enabled ? "Saved. Booking is live on your website's contact page." : "Saved." });
    } catch (e) {
      setNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Booking settings" actions={
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" className="accent-brand-600" checked={s.enabled} onChange={(e) => save({ ...s, enabled: e.target.checked })} />
        Online booking {s.enabled ? "on" : "off"}
      </label>
    }>
      <div className="grid gap-6">
        <div>
          <div className="mb-2 text-sm font-medium">Services customers can book</div>
          <div className="grid gap-2">
            {s.services.map((svc, i) => (
              <div key={i} className="flex flex-wrap gap-2 sm:flex-nowrap">
                <Input className="w-full min-w-0 sm:w-auto sm:flex-1" value={svc.name} placeholder="Service name" onChange={(e) => setS({ ...s, services: s.services.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} />
                <Select className="w-36" value={svc.duration_minutes} onChange={(e) => setS({ ...s, services: s.services.map((x, j) => j === i ? { ...x, duration_minutes: Number(e.target.value) } : x) })}>
                  {[15, 30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} min</option>)}
                </Select>
                <Button variant="ghost" onClick={() => setS({ ...s, services: s.services.filter((_, j) => j !== i) })}>Remove</Button>
              </div>
            ))}
            <div><Button size="sm" variant="secondary" onClick={() => setS({ ...s, services: [...s.services, { name: "", duration_minutes: 30 }] })}>Add service</Button></div>
          </div>
        </div>
        <div>
          <div className="mb-2 text-sm font-medium">Opening hours ({s.timezone})</div>
          <div className="grid gap-2">
            {DAYS.map(([key, label]) => {
              const window = s.weekly_hours[key]?.[0];
              return (
                <div key={key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 text-sm sm:grid-cols-[110px_auto_minmax(0,1fr)]">
                  <span>{label}</span>
                  <label className="flex items-center gap-1.5 text-stone-600">
                    <input type="checkbox" className="accent-brand-600" checked={Boolean(window)}
                      onChange={(e) => setS({ ...s, weekly_hours: { ...s.weekly_hours, [key]: e.target.checked ? [["09:00", "17:00"]] : [] } })} />
                    Open
                  </label>
                  {window ? (
                    <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
                      <Input type="time" className="min-w-0 flex-1 sm:w-32 sm:flex-none" value={window[0]} onChange={(e) => setS({ ...s, weekly_hours: { ...s.weekly_hours, [key]: [[e.target.value, window[1]]] } })} />
                      <span className="text-stone-400">to</span>
                      <Input type="time" className="min-w-0 flex-1 sm:w-32 sm:flex-none" value={window[1]} onChange={(e) => setS({ ...s, weekly_hours: { ...s.weekly_hours, [key]: [[window[0], e.target.value]] } })} />
                    </div>
                  ) : <span className="col-span-2 text-stone-400 sm:col-span-1">Closed</span>}
                </div>
              );
            })}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Time slot step">
            <Select value={s.slot_minutes} onChange={(e) => setS({ ...s, slot_minutes: Number(e.target.value) })}>
              {[15, 30, 60].map((m) => <option key={m} value={m}>Every {m} min</option>)}
            </Select>
          </Field>
          <Field label="Minimum notice">
            <Select value={s.lead_time_hours} onChange={(e) => setS({ ...s, lead_time_hours: Number(e.target.value) })}>
              {[0, 1, 2, 4, 12, 24, 48].map((h) => <option key={h} value={h}>{h} hours</option>)}
            </Select>
          </Field>
          <Field label="Confirmation">
            <Select value={s.auto_confirm ? "auto" : "manual"} onChange={(e) => setS({ ...s, auto_confirm: e.target.value === "auto" })}>
              <option value="auto">Confirm automatically</option>
              <option value="manual">I confirm each booking</option>
            </Select>
          </Field>
        </div>
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
        <div><Button busy={busy} onClick={() => save(s)}>Save settings</Button></div>
      </div>
    </Card>
  );
}

function Bookings() {
  const [settings, setSettings] = useState<BookingSettings | null>(null);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const since = new Date(Date.now() - 864e5).toISOString();
    api<Appointment[]>(`/customer/booking/appointments?start=${encodeURIComponent(since)}`).then(setAppointments);
  }, []);
  useEffect(() => {
    api<BookingSettings>("/customer/booking/settings").then(setSettings).catch((e) => setError(e.message));
    load();
  }, [load]);

  async function act(id: string, action: string) {
    try {
      await api(`/customer/booking/appointments/${id}/${action}`, { body: {} });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    }
  }

  return (
    <>
      <PageHeader title="Bookings" description="Let customers book appointments from your website." />
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      <div className="grid gap-6">
        <Card title="Upcoming appointments">
          {appointments.length === 0 ? <Empty>No upcoming appointments.</Empty> : (
            <Table head={["When", "Service", "Customer", "Status", ""]}>
              {appointments.map((a) => (
                <tr key={a.id}>
                  <Td className="whitespace-nowrap">{new Date(a.starts_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</Td>
                  <Td>{a.service_name}</Td>
                  <Td>
                    <div className="font-medium">{a.customer_name}</div>
                    <div className="text-xs text-stone-500">{[a.customer_email, a.customer_phone && `+${a.customer_phone}`].filter(Boolean).join(" · ")}</div>
                    {a.notes && <div className="text-xs text-stone-600">“{a.notes}”</div>}
                  </Td>
                  <Td><Badge tone={STATUS_TONE[a.status]}>{a.status}</Badge></Td>
                  <Td className="whitespace-nowrap text-right">
                    <div className="inline-flex gap-1.5">
                      {a.status === "pending" && <Button size="sm" onClick={() => act(a.id, "confirm")}>Confirm</Button>}
                      {a.status === "confirmed" && <Button size="sm" variant="secondary" onClick={() => act(a.id, "complete")}>Done</Button>}
                      {(a.status === "pending" || a.status === "confirmed") && <Button size="sm" variant="danger" onClick={() => act(a.id, "cancel")}>Cancel</Button>}
                    </div>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        {settings && <SettingsCard initial={settings} onSaved={setSettings} />}
      </div>
    </>
  );
}

export default function BookingsPage() {
  return <FeatureGate feature="booking"><Bookings /></FeatureGate>;
}
