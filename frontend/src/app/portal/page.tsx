"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Empty, Field, Input, Select, Stat, Textarea } from "@/components/ui";
import { ApiError, api, money } from "@/lib/api";
import { MediaLibrary, SeoPanel, Thumb } from "@/components/media";
import type { ContentBlock, CustomerDashboard, Media, Plan } from "@/lib/types";

const SECTION_LABELS: Record<string, string> = {
  hero: "Homepage banner", about: "About", services: "Services", faq: "FAQ", cta: "Call to action",
  contact: "Contact", testimonials: "Testimonials", gallery: "Gallery",
};
const TEXT_FIELDS: Record<string, string[]> = {
  hero: ["headline", "subheadline", "cta_label"],
  about: ["heading", "company_story", "mission_statement", "service_summary"],
  services: ["heading", "intro"],
  faq: ["heading"],
  cta: ["heading", "text", "button_label"],
  contact: ["heading", "intro"],
  testimonials: ["heading"],
  gallery: ["heading"],
};
const ITEM_FIELDS: Record<string, [string, string]> = {
  services: ["name", "description"], faq: ["question", "answer"], testimonials: ["author", "quote"],
};
const LONG = new Set(["company_story", "subheadline", "description", "answer", "quote", "text"]);
const label = (s: string) => s.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

type ImageRef = { asset_id: string; alt: string };

function ContentEditor({ onSaved, media }: { onSaved: () => void; media: Media[] }) {
  const [blocks, setBlocks] = useState<ContentBlock[]>([]);
  const [section, setSection] = useState("hero");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [status, setStatus] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [imageTouched, setImageTouched] = useState(false);

  useEffect(() => {
    api<ContentBlock[]>("/customer/content").then(setBlocks);
  }, []);
  useEffect(() => {
    setDraft(blocks.find((b) => b.section_key === section)?.content ?? {});
    setStatus(null);
    setImageTouched(false);
  }, [section, blocks]);

  const editable = blocks.filter((b) => b.section_key in TEXT_FIELDS);
  const itemKeys = ITEM_FIELDS[section];
  const items = (draft.items as Record<string, string>[] | undefined) ?? [];

  async function save() {
    setBusy(true);
    const fields = [...(TEXT_FIELDS[section] ?? []), ...(itemKeys ? ["items"] : []),
      ...(section === "gallery" ? ["images"] : []), ...(section === "hero" && imageTouched ? ["image"] : [])];
    const updates = Object.fromEntries(fields.filter((f) => f in draft).map((f) => [f, draft[f]]));
    try {
      setBlocks(await api<ContentBlock[]>("/customer/content", { method: "PUT", body: { section_key: section, updates } }));
      setStatus({ tone: "green", text: "Saved and published." });
      onSaved();
    } catch (err) {
      setStatus({ tone: "red", text: err instanceof ApiError ? err.message : "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Website content" actions={
      <Select value={section} onChange={(e) => setSection(e.target.value)} className="h-8 w-48">
        {editable.map((b) => <option key={b.section_key} value={b.section_key}>{SECTION_LABELS[b.section_key] ?? b.section_key}</option>)}
      </Select>
    }>
      <div className="grid gap-4">
        {(TEXT_FIELDS[section] ?? []).map((f) => (
          <Field key={f} label={label(f)}>
            {LONG.has(f) ? (
              <Textarea rows={3} value={String(draft[f] ?? "")} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} />
            ) : (
              <Input value={String(draft[f] ?? "")} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} />
            )}
          </Field>
        ))}
        {itemKeys && (
          <div className="grid gap-3">
            <div className="text-sm font-medium">Items</div>
            {items.map((item, i) => (
              <div key={i} className="grid gap-2 rounded-lg border border-line p-3">
                <Input placeholder={label(itemKeys[0])} value={item[itemKeys[0]] ?? ""}
                  onChange={(e) => setDraft({ ...draft, items: items.map((it, j) => j === i ? { ...it, [itemKeys[0]]: e.target.value } : it) })} />
                <Textarea rows={2} placeholder={label(itemKeys[1])} value={item[itemKeys[1]] ?? ""}
                  onChange={(e) => setDraft({ ...draft, items: items.map((it, j) => j === i ? { ...it, [itemKeys[1]]: e.target.value } : it) })} />
                <div><Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, items: items.filter((_, j) => j !== i) })}>Remove</Button></div>
              </div>
            ))}
            <div>
              <Button size="sm" variant="secondary" onClick={() => setDraft({ ...draft, items: [...items, { [itemKeys[0]]: "", [itemKeys[1]]: "" }] })}>
                Add item
              </Button>
            </div>
          </div>
        )}
        {section === "gallery" && (
          <div className="grid gap-2">
            <div className="text-sm font-medium">Photos shown in your gallery</div>
            {media.length === 0 ? <p className="text-sm text-stone-500">Upload photos below first.</p> : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                {media.map((m) => {
                  const images = (draft.images as ImageRef[] | undefined) ?? [];
                  const selected = images.some((i) => i.asset_id === m.id);
                  return (
                    <button key={m.id} type="button" aria-pressed={selected}
                      onClick={() => setDraft({ ...draft, images: selected ? images.filter((i) => i.asset_id !== m.id)
                        : [...images, { asset_id: m.id, alt: m.alt_text ?? "" }] })}
                      className={`rounded-lg p-0.5 ring-2 ${selected ? "ring-brand-600" : "ring-transparent"}`}>
                      <Thumb id={m.id} alt={m.alt_text ?? ""} />
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
        {section === "hero" && media.length > 0 && (
          <Field label="Banner image" hint="Use one of your photos instead of the generated artwork.">
            <Select value={(draft.image as ImageRef & { source?: string } | null)?.source === "upload"
              ? (draft.image as ImageRef).asset_id : ""}
              onChange={(e) => {
                const m = media.find((x) => x.id === e.target.value);
                setImageTouched(true);
                setDraft({ ...draft, image: m ? { asset_id: m.id, alt: m.alt_text ?? "" } : null });
              }}>
              <option value="">Generated artwork</option>
              {media.map((m) => <option key={m.id} value={m.id}>{m.alt_text || `Photo ${m.id.slice(0, 6)}`}</option>)}
            </Select>
          </Field>
        )}
        {status && <Alert tone={status.tone}>{status.text}</Alert>}
        <div><Button onClick={save} busy={busy}>Save and publish</Button></div>
      </div>
    </Card>
  );
}

function ProfileForm({ dashboard, onSaved }: { dashboard: CustomerDashboard; onSaved: (d: CustomerDashboard) => void }) {
  const b = dashboard.business;
  const [form, setForm] = useState({
    name: b.name ?? "", description: b.description ?? "", phone: b.phone ?? "", email: b.email ?? "",
    address: b.address ?? "", facebook: b.facebook ?? "",
  });
  const [status, setStatus] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      onSaved(await api<CustomerDashboard>("/customer/profile", { method: "PUT", body: { ...body, name: form.name } }));
      setStatus({ tone: "green", text: "Business details updated." });
    } catch (err) {
      setStatus({ tone: "red", text: err instanceof ApiError ? err.message : "Save failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Business profile">
      <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
        <Field label="Business name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Phone"><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
        <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="Facebook page"><Input value={form.facebook} onChange={(e) => setForm({ ...form, facebook: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Field label="Address"><Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field></div>
        <div className="sm:col-span-2"><Field label="Description"><Textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field></div>
        {status && <div className="sm:col-span-2"><Alert tone={status.tone}>{status.text}</Alert></div>}
        <div><Button type="submit" busy={busy}>Save details</Button></div>
      </form>
    </Card>
  );
}

function Plans({ current, onChanged }: { current: string; onChanged: () => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    api<Plan[]>("/billing/plans").then(setPlans);
  }, []);
  return (
    <Card title="Plan">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {plans.map((p) => (
          <div key={p.code} className={`rounded-lg border p-4 ${p.code === current ? "border-brand-500 bg-brand-50" : "border-line"}`}>
            <div className="flex items-center justify-between">
              <span className="font-semibold">{p.name}</span>
              {p.code === current && <Badge tone="green">current</Badge>}
            </div>
            <div className="mt-1 text-sm tabular-nums text-stone-600">{p.price_monthly_cents ? `${money(p.price_monthly_cents, p.currency)}/mo` : "Free"}</div>
            <p className="mt-2 text-xs text-stone-500">{p.description}</p>
            {p.code !== current && (
              <Button size="sm" variant="secondary" className="mt-3" busy={busy === p.code} onClick={async () => {
                setBusy(p.code);
                await api("/customer/subscription", { body: { plan: p.code } }).finally(() => setBusy(null));
                onChanged();
              }}>Switch</Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function PortalOverview() {
  const [dashboard, setDashboard] = useState<CustomerDashboard | null>(null);
  const [media, setMedia] = useState<Media[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<CustomerDashboard>("/customer/dashboard")
      .then(setDashboard)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load"));
    api<Media[]>("/customer/media").then(setMedia).catch(() => setMedia([]));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="grid gap-6">
        {error && <Alert tone="amber">{error}</Alert>}
        {dashboard && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">{dashboard.business.name}</h1>
                {dashboard.website?.url && (
                  <a href={dashboard.website.url} target="_blank" rel="noopener" className="text-sm text-brand-700 underline">
                    {dashboard.website.url}
                  </a>
                )}
              </div>
              {dashboard.website && <Badge>{dashboard.website.status}</Badge>}
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Visits (30d)" value={dashboard.stats.page_views_30d} />
              <Stat label="Leads (30d)" value={dashboard.stats.leads_30d} />
              <Stat label="Phone taps (30d)" value={dashboard.stats.phone_clicks_30d} />
              <Stat label="SEO score" value={dashboard.website?.seo_score ?? "—"} />
            </div>
            {dashboard.seo && <SeoPanel seo={dashboard.seo} />}
            <ContentEditor onSaved={load} media={media} />
            <MediaLibrary media={media} onChange={load} />
            <ProfileForm dashboard={dashboard} onSaved={setDashboard} />
            <Card title="Recent leads">
              {dashboard.recent_leads.length === 0 ? (
                <Empty>Messages from your website&apos;s contact form will appear here.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {dashboard.recent_leads.map((l) => (
                    <li key={l.id} className="py-3 text-sm">
                      <div className="flex justify-between gap-4">
                        <span className="font-medium">{l.name}</span>
                        <span className="text-stone-500">{new Date(l.created_at).toLocaleDateString()}</span>
                      </div>
                      <div className="text-stone-600">{[l.email, l.phone].filter(Boolean).join(" · ")}</div>
                      <p className="mt-1">{l.message}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Plans current={dashboard.customer.plan} onChanged={load} />
          </>
        )}
    </div>
  );
}
