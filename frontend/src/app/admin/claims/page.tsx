"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Button, Card, Empty, Table, Td, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Claim, ClaimStatus, Page } from "@/lib/types";

const TABS: { value: ClaimStatus | ""; label: string }[] = [
  { value: "manual_review", label: "Needs review" },
  { value: "pending_verification", label: "Awaiting verification" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "", label: "All" },
];

export default function ClaimsPage() {
  const [tab, setTab] = useState<ClaimStatus | "">("manual_review");
  const [data, setData] = useState<Page<Claim> | null>(null);
  const [notice, setNotice] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Page<Claim>>(`/claims?page_size=100${tab ? `&status_filter=${tab}` : ""}`).then(setData);
  }, [tab]);
  useEffect(load, [load]);

  async function review(claim: Claim, decision: "approve" | "reject") {
    const notes = decision === "reject" ? window.prompt("Reason for rejection (sent to audit log)") : null;
    if (decision === "reject" && notes === null) return;
    setBusy(`${claim.id}:${decision}`);
    try {
      await api(`/claims/${claim.id}/${decision}`, { body: { notes } });
      setNotice({ tone: "green", text: `Claim by ${claim.claimant_name} ${decision === "approve" ? "approved" : "rejected"}.` });
      load();
    } catch (err) {
      setNotice({ tone: "red", text: err instanceof ApiError ? err.message : "Request failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader title="Claims" description="Ownership requests. High-risk and document-based claims wait here for review." />
      <div className="mb-4 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
        {TABS.map((t) => (
          <button key={t.label} onClick={() => setTab(t.value)} className={cx(
            "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            tab === t.value ? "border-brand-600 text-ink" : "border-transparent text-stone-500 hover:text-ink",
          )}>{t.label}</button>
        ))}
      </div>
      {notice && <div className="mb-4"><Alert tone={notice.tone}>{notice.text}</Alert></div>}
      <Card>
        {data && data.items.length === 0 ? (
          <Empty>Nothing here.</Empty>
        ) : (
          <Table head={["Claimant", "Method", "Risk", "Evidence", "Status", ""]}>
            {data?.items.map((c) => (
              <tr key={c.id}>
                <Td>
                  <div className="font-medium">{c.claimant_name}</div>
                  <div className="text-xs text-stone-500">{c.claimant_email}{c.claimant_phone && ` · +${c.claimant_phone}`}</div>
                </Td>
                <Td className="text-stone-600">{c.method.replace("_", " ")}</Td>
                <Td>
                  <span title={c.risk_factors.join("\n")} className={cx(
                    "tabular-nums font-medium",
                    c.risk_score >= 60 ? "text-red-700" : c.risk_score >= 30 ? "text-amber-700" : "text-brand-700",
                  )}>{c.risk_score}</span>
                </Td>
                <Td className="max-w-56 truncate text-xs text-stone-600">
                  {Object.entries(c.evidence).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"}
                </Td>
                <Td><Badge>{c.status}</Badge></Td>
                <Td className="whitespace-nowrap text-right">
                  {c.status === "manual_review" && (
                    <div className="inline-flex gap-1.5">
                      <Button size="sm" variant="danger" busy={busy === `${c.id}:reject`} onClick={() => review(c, "reject")}>Reject</Button>
                      <Button size="sm" busy={busy === `${c.id}:approve`} disabled={!c.verified_at} onClick={() => review(c, "approve")}>Approve</Button>
                    </div>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
