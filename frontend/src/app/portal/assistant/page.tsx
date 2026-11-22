"use client";

import { useCallback, useEffect, useState } from "react";
import { FeatureGate } from "@/components/feature-gate";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Field, Input, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ChatbotSettings, Conversation, ConversationDetail, KnowledgeEntry } from "@/lib/types";

function SettingsCard() {
  const [s, setS] = useState<ChatbotSettings | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  useEffect(() => { api<ChatbotSettings>("/customer/chatbot/settings").then(setS); }, []);
  if (!s) return null;

  async function save(next: ChatbotSettings) {
    try {
      setS(await api<ChatbotSettings>("/customer/chatbot/settings", { method: "PUT", body: next }));
      setNotice({ tone: "green", text: next.enabled ? "Saved. The assistant is live on your website." : "Saved." });
    } catch (e) {
      setNotice({ tone: "red", text: e instanceof ApiError ? e.message : "Save failed" });
    }
  }

  return (
    <Card title="Assistant settings" actions={
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" className="accent-brand-600" checked={s.enabled} onChange={(e) => save({ ...s, enabled: e.target.checked })} />
        Assistant {s.enabled ? "on" : "off"}
      </label>
    }>
      <div className="grid gap-4">
        <Field label="Greeting"><Input value={s.greeting} onChange={(e) => setS({ ...s, greeting: e.target.value })} /></Field>
        <Field label="When it doesn't know the answer" hint="The assistant never guesses. It says this and offers to take the visitor's details.">
          <Textarea rows={2} value={s.handoff_message} onChange={(e) => setS({ ...s, handoff_message: e.target.value })} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="accent-brand-600" checked={s.collect_leads} onChange={(e) => setS({ ...s, collect_leads: e.target.checked })} />
          Save visitors&apos; names, phones and emails to Leads &amp; CRM
        </label>
        {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
        <div><Button onClick={() => save(s)}>Save</Button></div>
      </div>
    </Card>
  );
}

function KnowledgeCard() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [draft, setDraft] = useState({ title: "", content: "" });
  const [editing, setEditing] = useState<string | null>(null);
  const load = useCallback(() => { api<KnowledgeEntry[]>("/customer/chatbot/knowledge").then(setEntries); }, []);
  useEffect(load, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (editing) await api(`/customer/chatbot/knowledge/${editing}`, { method: "PUT", body: draft });
    else await api("/customer/chatbot/knowledge", { body: draft });
    setDraft({ title: "", content: "" });
    setEditing(null);
    load();
  }

  return (
    <Card title="What the assistant knows" actions={
      <Button size="sm" variant="secondary" onClick={async () => setEntries(await api<KnowledgeEntry[]>("/customer/chatbot/knowledge/rebuild", { body: {} }))}>
        Re-import from website
      </Button>
    }>
      <p className="mb-4 text-sm text-stone-600">Answers come only from this list. It&apos;s built from your website&apos;s FAQ, services and contact details. Add anything else customers often ask.</p>
      <form onSubmit={submit} className="mb-5 grid gap-2 rounded-lg border border-line p-3">
        <Input required placeholder="Question or topic, e.g. Do you deliver?" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        <Textarea required rows={2} placeholder="Answer" value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
        <div className="flex gap-2">
          <Button type="submit" size="sm">{editing ? "Save changes" : "Add"}</Button>
          {editing && <Button size="sm" variant="ghost" onClick={() => { setEditing(null); setDraft({ title: "", content: "" }); }}>Cancel</Button>}
        </div>
      </form>
      {entries.length === 0 ? <Empty>Nothing yet. Turn the assistant on to import your website content.</Empty> : (
        <ul className="divide-y divide-line">
          {entries.map((e) => (
            <li key={e.id} className="flex items-start justify-between gap-4 py-3 text-sm">
              <div>
                <div className="flex items-center gap-2 font-medium">{e.title}<Badge tone={e.source === "website" ? "gray" : "blue"}>{e.source}</Badge></div>
                <p className="mt-0.5 text-stone-600">{e.content}</p>
              </div>
              <div className="flex shrink-0 gap-2 text-xs">
                <button className="text-stone-600 hover:underline" onClick={() => { setEditing(e.id); setDraft({ title: e.title, content: e.content }); }}>Edit</button>
                <button className="text-red-700 hover:underline" onClick={async () => { await api(`/customer/chatbot/knowledge/${e.id}`, { method: "DELETE" }); load(); }}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ConversationsCard() {
  const [list, setList] = useState<Conversation[]>([]);
  const [open, setOpen] = useState<ConversationDetail | null>(null);
  useEffect(() => { api<Conversation[]>("/customer/chatbot/conversations").then(setList); }, []);
  return (
    <Card title="Recent conversations">
      {list.length === 0 ? <Empty>Conversations with website visitors will appear here.</Empty> : (
        <div className="grid gap-4 md:grid-cols-[240px_1fr]">
          <ul className="grid content-start gap-1">
            {list.map((c) => (
              <li key={c.id}>
                <button onClick={async () => setOpen(await api<ConversationDetail>(`/customer/chatbot/conversations/${c.id}`))}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-stone-50 ${open?.id === c.id ? "bg-brand-50" : ""}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span>{new Date(c.last_message_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                    {c.lead_captured && <Badge tone="green">lead</Badge>}
                  </div>
                  <div className="text-xs text-stone-500">{c.message_count} messages</div>
                </button>
              </li>
            ))}
          </ul>
          <div className="grid content-start gap-2 rounded-lg bg-stone-50 p-3">
            {open ? open.messages.map((m, i) => (
              <p key={i} className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${m.role === "user" ? "justify-self-end bg-brand-600 text-white" : "justify-self-start bg-white"}`}>
                {m.content}
              </p>
            )) : <p className="text-sm text-stone-500">Select a conversation.</p>}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function AssistantPage() {
  return (
    <FeatureGate feature="ai_chatbot">
      <PageHeader title="AI assistant" description="Answers visitors' questions from your own information, day and night, and passes leads to you." />
      <div className="grid gap-6">
        <SettingsCard />
        <KnowledgeCard />
        <ConversationsCard />
      </div>
    </FeatureGate>
  );
}
