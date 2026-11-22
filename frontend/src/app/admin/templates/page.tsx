"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Template } from "@/lib/types";

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Template[]>("/templates").then(setTemplates);
  }, []);
  useEffect(load, [load]);

  async function sync() {
    setBusy(true);
    try {
      const r = await api<{ templates_created: number; templates_updated: number; components_registered: number }>(
        "/templates/sync", { body: {} });
      setNotice({ tone: "green", text: `Synced: ${r.templates_created} new, ${r.templates_updated} updated, ${r.components_registered} components.` });
      load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Sync failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Templates"
        description="Master templates from /templates/manifests. Industry decides the template; AI only fills content."
        actions={<Button variant="secondary" busy={busy} onClick={sync}>Sync from repository</Button>}
      />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {templates.map((t) => (
          <Card key={t.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-semibold">{t.name}</div>
                <div className="font-mono text-xs text-stone-500">{t.slug}</div>
              </div>
              <div className="flex gap-1.5">
                {t.is_default && <Badge tone="blue">default</Badge>}
                <Badge>{t.status}</Badge>
              </div>
            </div>
            <div className="mt-4 flex overflow-hidden rounded-md ring-1 ring-line">
              {Object.entries(t.theme.palette ?? {}).slice(0, 6).map(([name, color]) => (
                <div key={name} title={`${name} ${color}`} className="h-6 flex-1" style={{ background: color }} />
              ))}
            </div>
            <p className="mt-3 text-sm text-stone-600">{t.description}</p>
            <div className="mt-3 text-xs text-stone-500">
              <span className="font-medium text-stone-700">Pages:</span> {t.pages.map((p) => p.title ?? p.slug).join(" · ")}
            </div>
            <div className="mt-1 text-xs text-stone-500">
              <span className="font-medium text-stone-700">Industries:</span> {t.industries.join(", ") || t.category}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
