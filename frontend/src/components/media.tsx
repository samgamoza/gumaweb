"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Empty, Input, cx } from "@/components/ui";
import { ApiError, api, apiBlobUrl } from "@/lib/api";
import type { ContentGap, Media } from "@/lib/types";

export function Thumb({ id, alt, className }: { id: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    apiBlobUrl(`/customer/media/${id}/file`).then((u) => { url = u; setSrc(u); }).catch(() => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [id]);
  return src
    ? <img src={src} alt={alt} className={cx("aspect-[3/2] w-full rounded-md object-cover", className)} />
    : <div className={cx("aspect-[3/2] w-full animate-pulse rounded-md bg-stone-100", className)} />;
}

export function MediaLibrary({ media, onChange }: { media: Media[]; onChange: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [alt, setAlt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      if (alt.trim()) form.append("alt_text", alt.trim());
      await api<Media>("/customer/media", { form });
      setAlt("");
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <Card title="Photos" actions={
      <>
        <Input placeholder="Describe the photo (alt text)" value={alt} onChange={(e) => setAlt(e.target.value)} className="h-8 w-56" />
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <Button size="sm" busy={busy} onClick={() => fileRef.current?.click()}>Upload</Button>
      </>
    }>
      {error && <div className="mb-3"><Alert>{error}</Alert></div>}
      {media.length === 0 ? (
        <Empty>Upload photos of your work, products or premises (JPEG, PNG or WebP, up to 5 MB). Then add them to your gallery.</Empty>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {media.map((m) => (
            <figure key={m.id} className="grid gap-1.5">
              <Thumb id={m.id} alt={m.alt_text ?? ""} />
              <figcaption className="flex items-center justify-between gap-2 text-xs text-stone-500">
                <span className="truncate">{m.alt_text || "No description"}</span>
                <button className="shrink-0 text-red-700 hover:underline" onClick={async () => {
                  await api(`/customer/media/${m.id}`, { method: "DELETE" });
                  onChange();
                }}>Delete</button>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </Card>
  );
}

const IMPACT_TONE = { high: "red", medium: "amber", low: "gray" } as const;

export function SeoPanel({ seo }: { seo: { score: number; content_gaps: ContentGap[] } }) {
  return (
    <Card title="Search visibility" actions={<span className="text-sm tabular-nums text-stone-600">Score <b className="text-ink">{seo.score}</b>/100</span>}>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-brand-100">
        <div className="h-full rounded-full bg-brand-600" style={{ width: `${seo.score}%` }} />
      </div>
      {seo.content_gaps.length === 0 ? (
        <p className="text-sm text-stone-600">Nice work. Your site covers everything search engines look for.</p>
      ) : (
        <ul className="grid gap-2.5">
          {seo.content_gaps.map((g) => (
            <li key={g.key} className="flex items-start gap-3 text-sm">
              <Badge tone={IMPACT_TONE[g.impact]}>{g.impact}</Badge>
              <span>{g.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
