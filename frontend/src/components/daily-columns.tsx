"use client";

import { useState } from "react";

/**
 * Single-series daily column chart. One hue (brand, validated vs the light surface), no legend
 * (the caller's title names the series), <=24px columns with a 4px rounded data-end, hairline grid,
 * whole-band hover targets with a tooltip, and a table view so values are never chart-only.
 */
export function DailyColumns({ data, label }: { data: { day: string; value: number }[]; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const max = Math.max(1, ...data.map((d) => d.value));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: Math.floor(top / step) + 1 }, (_, i) => i * step);
  const W = 720, H = 200, left = 32, bottom = 22, plotH = H - bottom - 8;
  const band = (W - left) / data.length;
  const colW = Math.min(24, band - 2);
  const y = (v: number) => 8 + plotH - (v / top) * plotH;
  const fmtDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <div className="text-sm text-stone-600">
          <span className="text-2xl font-semibold tabular-nums text-ink">{total}</span> {label.toLowerCase()} in {data.length} days
        </div>
        <button onClick={() => setAsTable((v) => !v)} className="text-xs font-medium text-stone-500 hover:text-ink">
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-stone-500"><th className="py-1.5">Day</th><th className="py-1.5 text-right">{label}</th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((d) => <tr key={d.day}><td className="py-1.5">{fmtDay(d.day)}</td><td className="py-1.5 text-right tabular-nums">{d.value}</td></tr>)}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${label} per day`} onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={left} x2={W} y1={y(t)} y2={y(t)} stroke="#e6e5e0" strokeWidth={1} />
                <text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-stone-500 text-[10px]">{t}</text>
              </g>
            ))}
            {data.map((d, i) => {
              const x = left + i * band + (band - colW) / 2;
              const h = Math.max(0, y(0) - y(d.value));
              const r = Math.min(4, h);
              return (
                <g key={d.day} onMouseEnter={() => setHover(i)}>
                  <rect x={left + i * band} y={8} width={band} height={plotH} fill="transparent" />
                  {d.value > 0 && (
                    <path
                      d={`M${x},${y(0)} v${-(h - r)} q0,${-r} ${r},${-r} h${colW - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                      className={hover === null || hover === i ? "fill-brand-600" : "fill-brand-600/40"}
                    />
                  )}
                  {/* weekly ticks + both ends; drop a weekly tick that would crowd the end label */}
                  {(i === 0 || i === data.length - 1 || (i % 7 === 0 && data.length - 1 - i >= 4)) && (
                    <text x={i === 0 ? left : i === data.length - 1 ? W : left + i * band + band / 2} y={H - 6}
                      textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}
                      className="fill-stone-500 text-[10px]">{fmtDay(d.day)}</text>
                  )}
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div
              className="pointer-events-none absolute -translate-x-1/2 rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-sm"
              style={{ left: `${((left + hover * band + band / 2) / W) * 100}%`, top: 0 }}
            >
              <div className="font-semibold tabular-nums">{data[hover].value}</div>
              <div className="text-stone-500">{fmtDay(data[hover].day)}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function niceStep(max: number) {
  const raw = max / 4;
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  return Math.max(1, [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? pow * 10); // counts: integer ticks
}
