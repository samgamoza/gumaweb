"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, cx } from "@/components/ui";
import { ApiError, api, apiBlobUrl } from "@/lib/api";
import type { GooglePack, PresenceAsset, PresenceKit, PresencePost, SeoProfile } from "@/lib/types";

const BIO_LIMITS: Record<string, number> = { facebook: 101, instagram: 150, tiktok: 80, x: 160 };
const PLATFORM: Record<string, string> = { facebook: "Facebook intro", instagram: "Instagram bio", tiktok: "TikTok bio", x: "X bio" };

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button size="sm" variant="secondary" onClick={async () => {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    }}>{done ? "Copied" : "Copy"}</Button>
  );
}

function KitImage({ asset, version }: { asset: PresenceAsset; version: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (asset.locked) return;
    let url: string | null = null;
    apiBlobUrl(`/customer/presence/assets/${asset.name}.png?v=${version}`).then((u) => { url = u; setSrc(u); }).catch(() => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [asset.name, asset.locked, version]);
  return (
    <figure className="grid min-w-0 grid-cols-1 gap-2">
      <div className={cx("relative flex items-center justify-center overflow-hidden rounded-lg border border-line bg-[repeating-conic-gradient(#f5f5f4_0_25%,#fff_0_50%)] bg-[length:16px_16px]",
        asset.width / asset.height > 1.6 ? "aspect-[2.6/1]" : asset.height > asset.width ? "aspect-[9/12]" : "aspect-square")}>
        {asset.locked
          ? <span className="text-xs font-medium text-stone-500">Professional plan</span>
          : src ? <img src={src} alt={asset.label} className="h-full w-full object-contain" />
            : <div className="h-full w-full animate-pulse bg-stone-100" />}
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="min-w-0"><span className="font-medium">{asset.label}</span> <span className="text-stone-500">{asset.width}×{asset.height}</span></span>
        {src && <a href={src} download={`${asset.name}.png`} className="font-medium text-brand-700 hover:underline">Download</a>}
      </figcaption>
    </figure>
  );
}

function Upgrade({ onUpgraded }: { onUpgraded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Card>
      <div className="grid max-w-xl gap-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Available on Professional</p>
        <h2 className="text-lg font-semibold tracking-tight">A week of ready-made posts, your Google Business Profile listing, and a local SEO plan.</h2>
        {error && <Alert>{error}</Alert>}
        <div>
          <Button busy={busy} onClick={async () => {
            setBusy(true);
            try {
              await api("/customer/subscription", { body: { plan: "professional" } });
              onUpgraded();
            } catch (e) {
              setError(e instanceof ApiError ? e.message : "Upgrade failed");
            } finally {
              setBusy(false);
            }
          }}>Upgrade to Professional</Button>
        </div>
      </div>
    </Card>
  );
}

function Posts({ posts, assets, version }: { posts: PresencePost[]; assets: PresenceAsset[]; version: number }) {
  return (
    <Card title="Your first week of posts">
      <p className="mb-4 text-sm text-stone-600">Review each one, then post it on your Facebook or Instagram. Every post uses only information from your website.</p>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {posts.map((p) => {
          const asset = assets.find((a) => a.name === `post-${p.key}`);
          return (
            <div key={p.key} className="grid min-w-0 grid-cols-1 gap-3 rounded-lg border border-line p-3">
              <div className="text-sm font-medium">{p.title}</div>
              {asset && <KitImage asset={asset} version={version} />}
              <p className="whitespace-pre-line text-sm text-stone-700">{p.caption}</p>
              <div><CopyButton text={p.caption} /></div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Google({ g, checklist, onToggle }: { g: GooglePack; checklist: Record<string, string>; onToggle: (step: string, done: boolean) => void }) {
  const done = g.checklist.filter((c) => checklist[c.key]).length;
  return (
    <Card title="Google Business Profile" actions={<Badge tone={done === g.checklist.length ? "green" : "gray"}>{done}/{g.checklist.length} steps</Badge>}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="grid min-w-0 grid-cols-1 gap-4 text-sm">
          <p className="text-stone-600">Copy these into <a className="font-medium text-brand-700 hover:underline" href="https://business.google.com" target="_blank" rel="noreferrer">business.google.com</a>. They follow Google&apos;s listing rules, so your profile isn&apos;t flagged.</p>
          <Field label="Business name" value={g.name} warnings={g.name_issues} />
          <Field label="Primary category" value={g.primary_category ?? "Choose the category that best describes your business"} copy={!!g.primary_category} />
          {g.additional_categories.length > 0 && <Field label="Additional categories" value={g.additional_categories.join(", ")} />}
          <Field label="Description" value={g.description} warnings={g.description_issues} multiline />
          <Field label="Website" value={g.website} />
          {g.hours_missing
            ? <Alert tone="amber">Add your opening hours on Google. Set them under Bookings and they&apos;ll appear here, ready to copy.</Alert>
            : <Field label="Opening hours" value={g.hours.join("\n")} multiline />}
          <Field label="Services" value={g.services.map((s) => `${s.name}: ${s.description}`).join("\n")} multiline />
          <Field label="First update" value={g.posts[0]?.text ?? ""} />
        </div>
        <ul className="grid content-start gap-2 text-sm">
          {g.checklist.map((c) => (
            <li key={c.key}>
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-0.5 accent-brand-600" checked={!!checklist[c.key]} onChange={(e) => onToggle(c.key, e.target.checked)} />
                <span className={cx(checklist[c.key] && "text-stone-400 line-through")}>{c.label}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function Field({ label, value, warnings = [], multiline, copy = true }: { label: string; value: string; warnings?: string[]; multiline?: boolean; copy?: boolean }) {
  return (
    <div className="grid min-w-0 grid-cols-1 gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-stone-500">{label}</span>
        {copy && value && <CopyButton text={value} />}
      </div>
      <div className={cx("break-words rounded-md bg-stone-50 px-3 py-2", multiline && "whitespace-pre-line")}>{value}</div>
      {warnings.map((w) => <Alert key={w} tone="amber">{w}</Alert>)}
    </div>
  );
}

function Seo({ s }: { s: SeoProfile }) {
  return (
    <Card title="Local SEO profile" actions={s.site_score != null && <Badge tone={s.site_score >= 80 ? "green" : "amber"}>Website SEO {s.site_score}/100</Badge>}>
      <div className="grid grid-cols-1 gap-6 text-sm md:grid-cols-2">
        <div className="grid min-w-0 content-start gap-3 break-words">
          <h3 className="font-medium">Use exactly this everywhere you&apos;re listed</h3>
          <div className="rounded-md bg-stone-50 px-3 py-2 leading-relaxed">
            <div className="font-medium">{s.nap.name}</div>
            <div>{s.nap.address ?? "Add your address"}</div>
            <div>{s.nap.phone_local ?? "Add your phone number"}</div>
          </div>
          {s.consistency_issues.map((i) => <Alert key={i} tone="amber">{i}</Alert>)}
          <h3 className="mt-2 font-medium">Searches to win</h3>
          <ul className="grid gap-1">
            {s.keywords.map((k) => <li key={k.phrase} className="flex justify-between gap-3"><span>&ldquo;{k.phrase}&rdquo;</span><span className="text-stone-500">{k.page}</span></li>)}
          </ul>
        </div>
        <div className="grid content-start gap-3">
          <h3 className="font-medium">Where to get listed</h3>
          <ul className="grid gap-2">
            {s.citations.map((c) => (
              <li key={c.key} className="flex items-start justify-between gap-3 rounded-md border border-line px-3 py-2">
                <div>
                  <a href={c.url} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">{c.name}</a>
                  <div className="text-xs text-stone-500">{c.why}</div>
                </div>
                {c.status !== "unknown" && <Badge tone={c.status === "listed" ? "green" : "amber"}>{c.status}</Badge>}
              </li>
            ))}
          </ul>
          {s.content_gaps.length > 0 && (
            <>
              <h3 className="mt-2 font-medium">Improve your website</h3>
              <ul className="list-disc pl-5 text-stone-700">{s.content_gaps.map((g) => <li key={g.key}>{g.message}</li>)}</ul>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function PresencePage() {
  const [kit, setKit] = useState<PresenceKit | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api<PresenceKit>("/customer/presence").then(setKit).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load your kit"));
  }, []);
  useEffect(load, [load]);

  if (error) return <Alert>{error}</Alert>;
  if (!kit) return null;
  const visible = kit.assets.filter((a) => !a.name.startsWith("post-"));
  return (
    <>
      <PageHeader title="Online presence" description="Your logo, social media kit, Google listing and local SEO plan, made from your website." />
      <div className="mb-6 flex flex-wrap gap-2">
        {kit.tiers.full && (
          <Button busy={busy} onClick={async () => {
            setBusy(true);
            try {
              const url = await apiBlobUrl("/customer/presence/download.zip");
              const a = document.createElement("a");
              a.href = url;
              a.download = "presence-kit.zip";
              a.click();
              URL.revokeObjectURL(url);
            } finally {
              setBusy(false);
            }
          }}>Download everything (ZIP)</Button>
        )}
        <Button variant="secondary" onClick={async () => setKit(await api<PresenceKit>("/customer/presence/regenerate", { body: {} }))}>Refresh from my website</Button>
      </div>
      <div className="grid grid-cols-1 gap-6">
        <Card title="Logo and images">
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((a) => <KitImage key={a.name} asset={a} version={kit.version} />)}
          </div>
        </Card>
        <Card title="Bios">
          <div className="grid gap-4 md:grid-cols-2">
            {Object.entries(kit.social.bios).map(([platform, bio]) => (
              <div key={platform} className="grid gap-2">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="font-medium">{PLATFORM[platform] ?? platform}</span>
                  <span className="flex items-center gap-2 text-xs text-stone-500">{bio.length}/{BIO_LIMITS[platform]} <CopyButton text={bio} /></span>
                </div>
                <p className="whitespace-pre-line rounded-md bg-stone-50 px-3 py-2 text-sm">{bio}</p>
              </div>
            ))}
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">Hashtags</span>
            <span className="text-stone-600">{kit.social.hashtags.join(" ")}</span>
            <CopyButton text={kit.social.hashtags.join(" ")} />
          </div>
        </Card>
        {kit.tiers.full ? (
          <>
            <Posts posts={kit.social.posts} assets={kit.assets} version={kit.version} />
            {kit.google && <Google g={kit.google} checklist={kit.checklist} onToggle={async (step, done) => setKit(await api<PresenceKit>("/customer/presence/checklist", { method: "PUT", body: { step, done } }))} />}
            {kit.seo && <Seo s={kit.seo} />}
          </>
        ) : <Upgrade onUpgraded={load} />}
      </div>
    </>
  );
}
