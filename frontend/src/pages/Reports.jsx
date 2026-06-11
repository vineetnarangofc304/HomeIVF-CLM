import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Play, CaretDown, CaretRight } from "@phosphor-icons/react";
import { API, apiErr, todayStr } from "../lib/api";
import { Spinner, EmptyState } from "../components/Bits";

const DIMS = [
  ["user_id", "Caller"], ["tags", "Disposition Tag"], ["lead_stage", "Lead Stage"],
  ["source_lead", "Source"], ["follow_up_tag", "Follow-up Tag"], ["create_date:day", "Created Day"],
  ["create_date:month", "Created Month"], ["state_name", "State"], ["city", "City"],
  ["ads_platform", "Ads Platform"], ["campaign_name", "Campaign"], ["lost_reason_id", "Lost Reason"],
];

const PRESETS = [
  { name: "MTD Caller Performance", desc: "Caller × Disposition tags this month", rows: ["user_id"], cols: "tags", filters: () => ({ date_from: todayStr().slice(0, 7) + "-01" }) },
  { name: "Daily Incoming by Tag", desc: "Day-wise incoming with dispositions", rows: ["create_date:day"], cols: "tags", filters: () => ({ date_from: todayStr().slice(0, 7) + "-01" }) },
  { name: "Funnel by Lead Stage", desc: "Where leads sit in the funnel", rows: ["lead_stage"], cols: null, filters: () => ({}) },
  { name: "Caller × Lead Stage", desc: "Conversion progress per caller", rows: ["user_id"], cols: "lead_stage", filters: () => ({ date_from: todayStr().slice(0, 7) + "-01" }) },
  { name: "Campaign Performance", desc: "Leads by campaign and stage", rows: ["campaign_name"], cols: "lead_stage", filters: () => ({}) },
  { name: "Source Analysis", desc: "Lead source × stage", rows: ["source_lead"], cols: "lead_stage", filters: () => ({}) },
  { name: "Monthly Trend", desc: "Month × lead stage", rows: ["create_date:month"], cols: "lead_stage", filters: () => ({}) },
  { name: "Lost Reasons", desc: "Why leads were lost", rows: ["lost_reason_id"], cols: null, filters: () => ({ active: "false" }) },
];

export default function Reports() {
  const [row1, setRow1] = useState("user_id");
  const [row2, setRow2] = useState("");
  const [col, setCol] = useState("tags");
  const [dateFrom, setDateFrom] = useState(todayStr().slice(0, 7) + "-01");
  const [dateTo, setDateTo] = useState("");
  const [active, setActive] = useState("true");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState({});

  const run = async (rows = null, c = undefined, filters = null) => {
    setLoading(true);
    setExpanded({});
    try {
      const body = {
        rows: rows || [row1, row2].filter(Boolean),
        cols: c === undefined ? col || null : c,
        filters: filters || { date_from: dateFrom || undefined, date_to: dateTo || undefined, active },
      };
      const { data } = await API.post("/reports/pivot", body);
      setResult(data);
    } catch (e) {
      toast.error(apiErr(e));
    } finally { setLoading(false); }
  };

  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  const applyPreset = (p) => {
    setRow1(p.rows[0]); setRow2(p.rows[1] || ""); setCol(p.cols || "");
    const f = p.filters();
    setDateFrom(f.date_from || ""); setDateTo(f.date_to || ""); setActive(f.active || "true");
    run(p.rows, p.cols || null, { ...f, active: f.active || "true" });
  };

  return (
    <div className="p-6" data-testid="reports-page">
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Reports</h1>
      <p className="text-sm text-slate-500">Pivot any dimension — same power as your Odoo group-bys</p>

      <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
        {PRESETS.map((p) => (
          <button key={p.name} data-testid={`preset-${p.name.replace(/\s|×/g, "-")}`} onClick={() => applyPreset(p)}
            className="rounded-2xl border border-slate-200 bg-white p-3 text-left transition-all hover:-translate-y-[2px] hover:border-[#4A90E2]/40 hover:shadow-md">
            <p className="text-sm font-bold text-slate-800">{p.name}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{p.desc}</p>
          </button>
        ))}
      </div>

      <div className="mt-5 hivf-card p-4">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Rows</label>
            <select data-testid="pivot-row1-select" className="hivf-select mt-1 block" value={row1} onChange={(e) => setRow1(e.target.value)}>
              {DIMS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Sub-rows</label>
            <select data-testid="pivot-row2-select" className="hivf-select mt-1 block" value={row2} onChange={(e) => setRow2(e.target.value)}>
              <option value="">None</option>
              {DIMS.filter(([v]) => v !== row1).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Columns</label>
            <select data-testid="pivot-col-select" className="hivf-select mt-1 block" value={col} onChange={(e) => setCol(e.target.value)}>
              <option value="">Count only</option>
              {DIMS.filter(([v]) => v !== row1 && v !== row2).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">From</label>
            <input type="date" className="hivf-select mt-1 block" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} data-testid="pivot-date-from" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">To</label>
            <input type="date" className="hivf-select mt-1 block" value={dateTo} onChange={(e) => setDateTo(e.target.value)} data-testid="pivot-date-to" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Status</label>
            <select className="hivf-select mt-1 block" value={active} onChange={(e) => setActive(e.target.value)}>
              <option value="true">Active</option><option value="false">Lost</option><option value="all">All</option>
            </select>
          </div>
          <button data-testid="run-report-button" onClick={() => run()} className="hivf-btn-primary !py-2"><Play size={14} weight="fill" /> Run</button>
        </div>

        {loading ? <Spinner /> : !result ? null : result.rows.length === 0 ? (
          <EmptyState title="No data" subtitle="Try widening your date range" />
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm" data-testid="pivot-table">
              <thead>
                <tr className="border-b-2 border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
                  <th className="sticky left-0 bg-white py-2 pr-4">{DIMS.find(([v]) => v === row1)?.[1]}{row2 ? ` / ${DIMS.find(([v]) => v === row2)?.[1]}` : ""}</th>
                  {result.col_keys.map((c) => <th key={c} className="px-2 py-2 text-right">{c === "count" ? "Leads" : c}</th>)}
                  {result.col_keys.length > 1 && <th className="px-2 py-2 text-right font-extrabold">Total</th>}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <React.Fragment key={r.key}>
                    <tr className="border-b border-slate-100 font-semibold hover:bg-[#4A90E2]/5">
                      <td className="sticky left-0 bg-white py-1.5 pr-4 text-slate-800">
                        {r.children?.length > 0 ? (
                          <button onClick={() => setExpanded((e) => ({ ...e, [r.key]: !e[r.key] }))} className="inline-flex items-center gap-1">
                            {expanded[r.key] ? <CaretDown size={12} /> : <CaretRight size={12} />}{r.key}
                          </button>
                        ) : r.key}
                      </td>
                      {result.col_keys.map((c) => <td key={c} className="px-2 py-1.5 text-right text-slate-600">{(r.cells[c] || 0).toLocaleString("en-IN")}</td>)}
                      {result.col_keys.length > 1 && <td className="px-2 py-1.5 text-right font-extrabold text-slate-800">{r.total.toLocaleString("en-IN")}</td>}
                    </tr>
                    {expanded[r.key] && r.children?.map((ch) => (
                      <tr key={ch.key} className="border-b border-slate-50 bg-slate-50/50 text-slate-500">
                        <td className="sticky left-0 bg-slate-50 py-1 pl-6 pr-4">{ch.key}</td>
                        {result.col_keys.map((c) => <td key={c} className="px-2 py-1 text-right">{(ch.cells[c] || 0).toLocaleString("en-IN")}</td>)}
                        {result.col_keys.length > 1 && <td className="px-2 py-1 text-right font-bold">{ch.total.toLocaleString("en-IN")}</td>}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
                <tr className="border-t-2 border-slate-200 font-extrabold text-slate-900">
                  <td className="sticky left-0 bg-white py-2 pr-4">Total</td>
                  {result.col_keys.map((c) => <td key={c} className="px-2 py-2 text-right">{(result.col_totals[c] || 0).toLocaleString("en-IN")}</td>)}
                  {result.col_keys.length > 1 && <td className="px-2 py-2 text-right" data-testid="pivot-grand-total">{result.grand_total.toLocaleString("en-IN")}</td>}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
