"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Call, VoiceSettings } from "@/lib/types";

const OUTCOME_TONE: Record<string, "green" | "blue" | "amber" | "gray"> = {
  booked: "green", message: "amber", answered: "blue", transferred: "blue", abandoned: "gray",
};

function SettingsCard() {
  const [s, setS] = useState<VoiceSettings | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  useEffect(() => { api<VoiceSettings>("/customer/voice/settings").then(setS); }, []);
  if (!s) return null;
  async function save(next: VoiceSettings) {
    try {
      setS(await api<VoiceSettings>("/customer/voice/settings", { method: "PUT", body: next }));
      setNotice({ tone: "green", text: "Saved." });
    } catch (e) {
      setNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Save failed" });
    }
  }
  return (
    <Card title="Phone settings" actions={
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" className="accent-brand-600" checked={s.enabled} onChange={(e) => save({ ...s, enabled: e.target.checked })} />
        Receptionist {s.enabled ? "on" : "off"}
      </label>
    }>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Receptionist phone number" hint="The number your telephony provider routes to GumaWeb.">
          <Input value={s.phone_number ?? ""} onChange={(e) => setS({ ...s, phone_number: e.target.value })} placeholder="0917 555 0000" />
        </Field>
        <Field label="Transfer calls to" hint="When a caller asks for a person.">
          <Input value={s.forward_number ?? ""} onChange={(e) => setS({ ...s, forward_number: e.target.value })} placeholder="Your mobile number" />
        </Field>
        {notice && <div className="sm:col-span-2"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
        <div><Button onClick={() => save(s)}>Save</Button></div>
      </div>
    </Card>
  );
}

function Simulator({ onEnded }: { onEnded: () => void }) {
  const [callId, setCallId] = useState<string | null>(null);
  const [lines, setLines] = useState<{ who: "caller" | "assistant"; text: string }[]>([]);
  const [text, setText] = useState("");
  const [ended, setEnded] = useState(false);
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { logRef.current?.scrollTo(0, logRef.current.scrollHeight); }, [lines]);

  async function start() {
    const r = await api<{ call_id: string; say: string }>("/customer/voice/test-call", { body: { caller: "09170000000" } });
    setCallId(r.call_id);
    setLines([{ who: "assistant", text: r.say }]);
    setEnded(false);
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!callId || !text.trim()) return;
    const said = text.trim();
    setLines((l) => [...l, { who: "caller", text: said }]);
    setText("");
    setBusy(true);
    try {
      const r = await api<{ say: string; action: string; transfer_to: string | null }>(`/customer/voice/test-call/${callId}/turn`, { body: { text: said } });
      setLines((l) => [...l, { who: "assistant", text: r.say + (r.action === "transfer" ? ` [transferring to +${r.transfer_to}]` : "") }]);
      if (r.action !== "continue") {
        setEnded(true);
        onEnded();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Try it" actions={<Button size="sm" variant="secondary" onClick={start}>{callId ? "New call" : "Start a test call"}</Button>}>
      {!callId ? (
        <p className="text-sm text-stone-600">Have a conversation with your receptionist exactly as a caller would. Type what a caller would say, e.g. &quot;I&apos;d like to book an appointment&quot;. Bookings made here are real.</p>
      ) : (
        <div className="grid gap-3">
          <div ref={logRef} className="grid max-h-80 gap-2 overflow-y-auto rounded-lg bg-stone-50 p-3">
            {lines.map((l, i) => (
              <p key={i} className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${l.who === "caller" ? "justify-self-end bg-brand-600 text-white" : "justify-self-start bg-white"}`}>{l.text}</p>
            ))}
          </div>
          {ended ? <Alert tone="green">Call ended. It appears in the call log below.</Alert> : (
            <form onSubmit={send} className="flex gap-2">
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="What the caller says..." autoFocus />
              <Button type="submit" busy={busy}>Say</Button>
            </form>
          )}
        </div>
      )}
    </Card>
  );
}

function CallLog({ calls }: { calls: Call[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card title="Call log">
      {calls.length === 0 ? <Empty>Calls answered by your receptionist will appear here, with a summary of each.</Empty> : (
        <ul className="divide-y divide-line">
          {calls.map((c) => (
            <li key={c.id} className="py-3 text-sm">
              <button className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setOpen(open === c.id ? null : c.id)}>
                <div>
                  <div className="font-medium">{c.caller_number ? `+${c.caller_number}` : "Unknown caller"} {c.is_test && <span className="text-xs font-normal text-stone-500">(test)</span>}</div>
                  <div className="text-stone-600">{c.summary ?? "In progress"}</div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-stone-500">
                  {c.outcome && <Badge tone={OUTCOME_TONE[c.outcome] ?? "gray"}>{c.outcome}</Badge>}
                  {new Date(c.started_at).toLocaleString()}
                </div>
              </button>
              {open === c.id && (
                <div className="mt-2 grid gap-1 rounded-lg bg-stone-50 p-3 text-xs">
                  {c.transcript.map((t, i) => <p key={i}><span className="font-semibold">{t.speaker === "caller" ? "Caller" : "Receptionist"}:</span> {t.text}</p>)}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Receptionist() {
  const [calls, setCalls] = useState<Call[]>([]);
  const load = useCallback(() => { api<Call[]>("/customer/voice/calls").then(setCalls); }, []);
  useEffect(load, [load]);
  return (
    <>
      <PageHeader title="AI receptionist" description="Answers your phone, books appointments, answers questions and takes messages, day and night." />
      <div className="grid gap-6">
        <Simulator onEnded={load} />
        <SettingsCard />
        <CallLog calls={calls} />
      </div>
    </>
  );
}

export default function ReceptionistPage() {
  return <FeatureGate feature="voice_receptionist"><Receptionist /></FeatureGate>;
}
