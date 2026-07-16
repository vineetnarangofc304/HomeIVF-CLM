import React, { useEffect, useState } from "react";
import { Gauge, ArrowsClockwise, TrendUp } from "@phosphor-icons/react";
import { API, apiErr, fmtDay } from "../lib/api";
import { toast } from "sonner";

const nf = (n) => (n ?? 0).toLocaleString("en-IN");

// Section palette — matches the requested colour coding
// (Yellow/Valid, Red/Contact Attempt, Orange/Contacted, Green/Converted, Grey/Closed)
const PALETTE = {
  yellow: { bar: "bg-amber-400", head: "bg-amber-50", ring: "border-amber-200", text: "text-amber-900", chip: "bg-amber-100 text-amber-800" },
  red: { bar: "bg-rose-500", head: "bg-rose-50", ring: "border-rose-200", text: "text-rose-900", chip: "bg-rose-100 text-rose-800" },
  orange: { bar: "bg-orange-500", head: "bg-orange-50", ring: "border-orange-200", text: "text-orange-900", chip: "bg-orange-100 text-orange-800" },
  green: { bar: "bg-emerald-500", head: "bg-emerald-50", ring: "border-emerald-200", text: "text-emerald-900", chip: "bg-emerald-100 text-emerald-800" },
  grey: { bar: "bg-slate-400", head: "bg-slate-50", ring: "border-slate-200", text: "text-slate-800", chip: "bg-slate-200 text-slate-700" },
};

const TotalCard = ({ label, value, hint, accent }) => (
  <div className="hivf-card p-4" data-testid={`kpi-total-${label.toLowerCase()}`}>
    <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
    <p className={`mt-1 font-display text-3xl font-extrabold ${accent}`}>{value}</p>
    <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>
  </div>
);

function SectionCard({ section, totalMtd }) {
  const c = PALETTE[section.color] || PALETTE.grey;
  const pct = (v) => (totalMtd ? Math.round((v / totalMtd) * 100) : 0);
  return (
    <div className={`overflow-hidden rounded-2xl border bg-white shadow-sm ${c.ring}`} data-testid={`kpi-section-${section.key}`}>
      <div className={`flex items-center justify-between gap-2 px-4 py-3 ${c.head}`}>
        <div className="flex items-center gap-2">
          <span className={`h-3 w-3 rounded-full ${c.bar}`} />
          <div>
            <h3 className={`font-display text-sm font-extrabold ${c.text}`}>{section.title}</h3>
            {section.subtitle && <p className="text-[11px] text-slate-500">{section.subtitle}</p>}
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${c.chip}`} data-testid={`kpi-section-total-${section.key}`}>
          MTD {nf(section.totals.mtd)}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="px-4 py-2 text-left font-bold">Sub Status</th>
              <th className="px-3 py-2 text-right font-bold">FTD</th>
              <th className="px-3 py-2 text-right font-bold">MTD</th>
              <th className="px-3 py-2 text-right font-bold">YTD</th>
              <th className="px-4 py-2 text-right font-bold">% (MTD)</th>
            </tr>
          </thead>
          <tbody>
            {section.rows.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-3 text-center text-xs text-slate-400">No sub-statuses mapped</td></tr>
            )}
            {section.rows.map((r) => (
              <tr key={r.label} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60" data-testid={`kpi-row-${section.key}`}>
                <td className="px-4 py-2 text-slate-700">{r.label}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{nf(r.ftd)}</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-slate-800">{nf(r.mtd)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{nf(r.ytd)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-slate-500">{pct(r.mtd)}%</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className={`border-t-2 ${c.ring} font-bold`}>
              <td className={`px-4 py-2 ${c.text}`}>Total</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">{nf(section.totals.ftd)}</td>
              <td className={`px-3 py-2 text-right tabular-nums ${c.text}`}>{nf(section.totals.mtd)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">{nf(section.totals.ytd)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-slate-500">{pct(section.totals.mtd)}%</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

export default function KpiOverview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    API.get("/reports/kpi-overview")
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(apiErr(e)))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const totalMtd = data?.total?.mtd || 0;

  return (
    <div className="space-y-5 p-6" data-testid="kpi-overview-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Gauge size={24} weight="fill" className="text-[#4A90E2]" />
          <div>
            <h1 className="font-display text-2xl font-extrabold text-slate-900">KPI Performance Overview</h1>
            <p className="text-sm text-slate-500">
              FTD = today{data ? ` (${fmtDay(data.today)})` : ""} · MTD = this month · YTD = this year · by lead creation date
            </p>
          </div>
        </div>
        <button onClick={load} disabled={loading} data-testid="kpi-refresh-button"
          className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-600 transition hover:border-[#4A90E2] hover:text-[#4A90E2] disabled:opacity-50">
          <ArrowsClockwise size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {loading && !data ? (
        <div className="hivf-card p-10 text-center text-slate-400" data-testid="kpi-loading">Loading KPI report…</div>
      ) : data ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <TotalCard label="FTD" value={nf(data.total.ftd)} hint="Leads created today" accent="text-slate-900" />
            <TotalCard label="MTD" value={nf(data.total.mtd)} hint="Leads created this month" accent="text-[#4A90E2]" />
            <TotalCard label="YTD" value={nf(data.total.ytd)} hint="Leads created this year" accent="text-[#8B5CF6]" />
          </div>

          {/* Conversion funnel */}
          <div className="overflow-hidden rounded-2xl border border-emerald-200 bg-white shadow-sm" data-testid="kpi-conversion">
            <div className="flex items-center gap-2 bg-emerald-600 px-4 py-3">
              <TrendUp size={16} weight="bold" className="text-white" />
              <h3 className="font-display text-sm font-extrabold text-white">Conversion Metrics (MTD)</h3>
            </div>
            <div className="grid grid-cols-1 gap-px bg-slate-100 sm:grid-cols-2 lg:grid-cols-4">
              {data.conversion.map((m) => (
                <div key={m.label} className="bg-white p-4" data-testid="kpi-conversion-metric">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{m.label}</p>
                  <p className="mt-1 font-display text-2xl font-extrabold text-emerald-600">{m.pct}%</p>
                  <p className="text-[11px] text-slate-400">{nf(m.num)} of {nf(m.den)}</p>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(m.pct, 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Stage sections */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {data.sections.map((s) => (
              <SectionCard key={s.key} section={s} totalMtd={totalMtd} />
            ))}
          </div>

          <p className="text-[11px] text-slate-400">
            Sub-statuses are grouped into stages using your Disposition Tag → Stage mapping (Admin → Dropdowns).
            "Valid Leads" is a computed cross-stage bucket. Percentages are of the month-to-date total ({nf(totalMtd)}).
          </p>
        </>
      ) : (
        <div className="hivf-card p-10 text-center text-slate-400" data-testid="kpi-empty">No data available.</div>
      )}
    </div>
  );
}
