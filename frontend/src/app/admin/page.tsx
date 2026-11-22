"use client";

import { useEffect, useState } from "react";
import { DailyColumns } from "@/components/daily-columns";
import { PageHeader } from "@/components/page-header";
import { Alert, Badge, Card, Stat, Table, Td, cx } from "@/components/ui";
import { api, money } from "@/lib/api";
import type { AiUsage, DayPoint, IndustryBreakdown, Overview, TemplatePerformance } from "@/lib/types";

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const compact = (n: number) => new Intl.NumberFormat("en", { notation: "compact" }).format(n);

const FUNNEL: [string, string][] = [
  ["outreach_sent", "Outreach sent"],
  ["opens", "Opened"],
  ["clicks", "Clicked"],
  ["claims_started", "Claims started"],
  ["claims_completed", "Claims completed"],
];

const METRICS: [keyof Omit<DayPoint, "day">, string][] = [
  ["published", "Sites published"],
  ["generated", "Sites generated"],
  ["discovered", "Businesses discovered"],
  ["claims_completed", "Claims completed"],
  ["page_views", "Site visits"],
  ["leads", "Leads"],
];

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [series, setSeries] = useState<DayPoint[]>([]);
  const [templates, setTemplates] = useState<TemplatePerformance[]>([]);
  const [industries, setIndustries] = useState<IndustryBreakdown[]>([]);
  const [ai, setAi] = useState<AiUsage | null>(null);
  const [metric, setMetric] = useState<(typeof METRICS)[number]>(METRICS[0]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<Overview>("/analytics/overview").then(setData),
      api<DayPoint[]>("/analytics/timeseries?days=30").then(setSeries),
      api<TemplatePerformance[]>("/analytics/templates").then(setTemplates),
      api<IndustryBreakdown[]>("/analytics/industries").then(setIndustries),
      api<AiUsage>("/analytics/ai").then(setAi),
    ]).catch((e) => setError(e.message));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return null;
  const k = data.kpis;
  const funnelMax = Math.max(1, ...FUNNEL.map(([key]) => data.funnel[key] ?? 0));

  return (
    <>
      <PageHeader title="Overview" description="Factory output and claim-first acquisition at a glance." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Businesses" value={k.businesses} hint={`${k.generate_candidates} generate candidates`} />
        <Stat label="Sites generated" value={k.generated_sites} hint={`${k.published_sites} published`} />
        <Stat label="Sites claimed" value={k.claimed_sites} hint={`claim rate ${pct(k.claim_rate)}`} />
        <Stat label="Pending reviews" value={k.pending_claims} />
        <Stat label="Paying customers" value={k.paid_sites} hint={`conversion ${pct(k.paid_conversion_rate)}`} />
        <Stat label="MRR" value={money(k.monthly_recurring_revenue_cents)} />
        <Stat label="ARPB" value={money(k.average_revenue_per_business_cents)} hint="per paying business" />
        <Stat label="Site visits (30d)" value={data.page_views_30d} />
      </div>

      <Card className="mt-6" title="Last 30 days" actions={
        <div role="tablist" className="flex flex-wrap gap-1">
          {METRICS.map((m) => (
            <button key={m[0]} role="tab" aria-selected={metric[0] === m[0]} onClick={() => setMetric(m)}
              className={cx("rounded-md px-2 py-1 text-xs font-medium",
                metric[0] === m[0] ? "bg-brand-50 text-brand-900" : "text-stone-500 hover:text-ink")}>
              {m[1]}
            </button>
          ))}
        </div>
      }>
        <DailyColumns label={metric[1]} data={series.map((d) => ({ day: d.day, value: d[metric[0]] }))} />
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Acquisition funnel">
          <div className="grid gap-3">
            {FUNNEL.map(([key, label]) => {
              const value = data.funnel[key] ?? 0;
              return (
                <div key={key} className="grid grid-cols-[140px_1fr_56px] items-center gap-3 text-sm">
                  <span className="text-stone-600">{label}</span>
                  <div className="h-2.5 overflow-hidden rounded-full bg-stone-100">
                    <div className="h-full rounded-full bg-brand-600" style={{ width: `${(value / funnelMax) * 100}%` }} />
                  </div>
                  <span className="text-right tabular-nums">{value}</span>
                </div>
              );
            })}
          </div>
        </Card>

        {ai && (
          <Card title="AI factory" actions={<Badge tone={ai.enabled ? "green" : "gray"}>{ai.enabled ? "enabled" : "templates only"}</Badge>}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div><div className="text-xs text-stone-500">AI-written sections</div><div className="text-lg font-semibold tabular-nums">{pct(ai.ai_section_share)}</div></div>
              <div><div className="text-xs text-stone-500">Tokens per site</div><div className="text-lg font-semibold tabular-nums">{compact(ai.tokens_per_site)}</div></div>
              <div><div className="text-xs text-stone-500">Library images</div><div className="text-lg font-semibold tabular-nums">{ai.library_images}</div></div>
              <div><div className="text-xs text-stone-500">Image reuses</div><div className="text-lg font-semibold tabular-nums">{compact(ai.library_image_uses)}</div></div>
            </div>
            {ai.models.length > 0 && (
              <div className="mt-4">
                <Table head={["Task", "Model", "Calls", "Accepted", "Tokens", "Avg latency"]}>
                  {ai.models.map((m) => (
                    <tr key={`${m.task}-${m.model}`}>
                      <Td>{m.task}</Td>
                      <Td className="font-mono text-xs">{m.model}</Td>
                      <Td className="tabular-nums">{m.calls}</Td>
                      <Td className="tabular-nums">{m.accepted}</Td>
                      <Td className="tabular-nums">{compact(m.prompt_tokens + m.completion_tokens)}</Td>
                      <Td className="tabular-nums">{(m.avg_latency_ms / 1000).toFixed(1)}s</Td>
                    </tr>
                  ))}
                </Table>
              </div>
            )}
          </Card>
        )}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card title="Templates">
          <Table head={["Template", "Sites", "Claimed", "Claim rate", "Avg quality"]}>
            {templates.map((t) => (
              <tr key={t.slug}>
                <Td><div className="font-medium">{t.name}</div><div className="font-mono text-xs text-stone-500">{t.slug}</div></Td>
                <Td className="tabular-nums">{t.sites}</Td>
                <Td className="tabular-nums">{t.claimed}</Td>
                <Td className="tabular-nums">{t.published ? pct(t.claim_rate) : "—"}</Td>
                <Td className="tabular-nums">{t.avg_quality ?? "—"}</Td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="Industries">
          <Table head={["Industry", "Businesses", "Candidates", "Sites", "Claimed", "Avg score"]}>
            {industries.map((i) => (
              <tr key={i.industry}>
                <Td className="font-medium">{i.industry.replaceAll("_", " ")}</Td>
                <Td className="tabular-nums">{i.businesses}</Td>
                <Td className="tabular-nums">{i.candidates}</Td>
                <Td className="tabular-nums">{i.sites}</Td>
                <Td className="tabular-nums">{i.claimed}</Td>
                <Td className="tabular-nums">{i.avg_score ?? "—"}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
