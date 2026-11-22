"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, ScoreBar, Table, Td } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Page, WebsiteSummary } from "@/lib/types";

export default function WebsitesPage() {
  const [data, setData] = useState<Page<WebsiteSummary> | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Page<WebsiteSummary>>("/websites?page_size=100").then(setData);
  }, []);
  useEffect(load, [load]);

  async function act(w: WebsiteSummary, action: "publish" | "regenerate" | "unpublish") {
    setBusy(`${w.id}:${action}`);
    setNotice(null);
    try {
      await api(`/websites/${w.id}/${action}`, { body: action === "regenerate" ? { publish: false } : {} });
      setNotice({ tone: "green", text: `${w.subdomain}: ${action} complete.` });
      load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader title="Websites" description="Generated sites, their quality gate, and publication state." />
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
      <Card>
        {data && data.items.length === 0 ? (
          <Empty>No websites yet. Generate one from the Businesses page.</Empty>
        ) : (
          <Table head={["Website", "Template", "Quality", "Version", "Status", ""]}>
            {data?.items.map((w) => (
              <tr key={w.id}>
                <Td>
                  <div className="font-medium">{w.business_name}</div>
                  {w.url ? (
                    <a href={w.url} target="_blank" rel="noopener" className="text-xs text-brand-700 underline">{w.subdomain}</a>
                  ) : <span className="text-xs text-stone-500">{w.subdomain}</span>}
                </Td>
                <Td className="font-mono text-xs text-stone-600">{w.template_slug}</Td>
                <Td><span title={w.quality_report?.issues.join("\n")}><ScoreBar value={w.quality_score} /></span></Td>
                <Td className="tabular-nums">v{w.version}</Td>
                <Td>
                  <div className="flex gap-1.5">
                    <Badge>{w.status}</Badge>
                    {w.is_claimed && <Badge tone="green">claimed</Badge>}
                  </div>
                </Td>
                <Td className="whitespace-nowrap text-right">
                  <div className="inline-flex gap-1.5">
                    <Button size="sm" variant="secondary" busy={busy === `${w.id}:regenerate`} onClick={() => act(w, "regenerate")}>Regenerate</Button>
                    {w.status === "published" ? (
                      <Button size="sm" variant="danger" busy={busy === `${w.id}:unpublish`} onClick={() => act(w, "unpublish")}>Unpublish</Button>
                    ) : (
                      <Button size="sm" busy={busy === `${w.id}:publish`} onClick={() => act(w, "publish")}>Publish</Button>
                    )}
                  </div>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
