import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Play, CaretDown, CaretRight, CaretUp, ChartBar, ChartLineUp, FileXls, FilePdf } from "@phosphor-icons/react";
import { API, apiErr, todayStr, dimFilterParams, leadsUrl } from "../lib/api";
import { useAuth, useCatalogMaps } from "../context/AuthContext";
import { Spinner, EmptyState } from "../components/Bits";
import Analytics from "../components/Analytics";

export const DIMS = [
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

const EMPTY_FILTERS = {
  date_from: todayStr().slice(0, 7) + "-01", date_to: "", active: "true",
  user_id: "", tags: "", lead_stage: "", source_lead: "", campaign_name: "",
  ads_platform: "", state_name: "", city: "", follow_up_tag: "",
};

export default function Reports() {
  const [tab, setTab] = useState("pivot");
  return (
    <div className="p-6" data-testid="reports-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-slate-900">Reports</h1>
          <p className="text-sm text-slate-500">Pivot any dimension · click any number to open the leads behind it</p>
        </div>
        <div className="flex overflow-hidden rounded-full border border-slate-200 bg-white">
          <button data-testid="reports-tab-pivot" onClick={() => setTab("pivot")}
            className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-bold transition-colors ${tab === "pivot" ? "bg-[#4A90E2] text-white" : "text-slate-500 hover:bg-slate-50"}`}>
            <ChartBar size={15} /> Pivot Builder
          </button>
          <button data-testid="reports-tab-analytics" onClick={() => setTab("analytics")}
            className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-bold transition-colors ${tab === "analytics" ? "bg-[#8B5CF6] text-white" : "text-slate-500 hover:bg-slate-50"}`}>
            <ChartLineUp size={15} /> Visual Analytics
          </button>
        </div>
      </div>
      <ExportBar />
      {tab === "pivot" ? <PivotBuilder /> : <Analytics />}
    </div>
  );
}

function ExportBar() {
  const [from, setFrom] = useState(todayStr().slice(0, 7) + "-01");
  const [to, setTo] = useState(todayStr());
  const [busy, setBusy] = useState("");

  const download = async (kind) => {
    setBusy(kind);
    try {
      const url = kind === "xlsx"
        ? `/export/leads.xlsx?date_from=${from}&date_to=${to}&active=all`
        : `/export/report.pdf?date_from=${from}&date_to=${to}`;
      const res = await API.get(url, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = kind === "xlsx" ? `homeivf_leads_${to}.xlsx` : `homeivf_report_${to}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      toast.success(kind === "xlsx" ? "Excel exported" : "PDF report exported");
    } catch (e) { toast.error(apiErr(e)); } finally { setBusy(""); }
  };

  return (
    <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="export-bar">
      <div>
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">From</label>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="hivf-input !py-1.5 !w-40 text-sm" data-testid="export-date-from" />
      </div>
      <div>
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">To</label>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="hivf-input !py-1.5 !w-40 text-sm" data-testid="export-date-to" />
      </div>
      <button onClick={() => download("xlsx")} disabled={busy} className="hivf-btn-secondary !py-2" data-testid="export-excel-button">
        <FileXls size={16} className="text-emerald-600" /> {busy === "xlsx" ? "Exporting…" : "Export Excel"}
      </button>
      <button onClick={() => download("pdf")} disabled={busy} className="hivf-btn-secondary !py-2" data-testid="export-pdf-button">
        <FilePdf size={16} className="text-rose-600" /> {busy === "pdf" ? "Generating…" : "PDF Report"}
      </button>
    </div>
  );
}

function PivotBuilder() {
  const navigate = useNavigate();
  const { catalogs } = useCatalogMaps();
  const { user } = useAuth();
  const [row1, setRow1] = useState("user_id");
  const [row2, setRow2] = useState("");
  const [col, setCol] = useState("tags");
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [sortCol, setSortCol] = useState(null); // null = by total
  const [sortDir, setSortDir] = useState(-1);

  const setF = (k, v) => setFilters((f) => ({ ...f, [k]: v }));

  const cleanFilters = (f) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "" && v != null));

  const run = async (rows = null, c = undefined, f = null) => {
    setLoading(true);
    setExpanded({});
    setSortCol(null);
    try {
      const body = {
        rows: rows || [row1, row2].filter(Boolean),
        cols: c === undefined ? col || null : c,
        filters: cleanFilters(f || filters),
      };
      const { data } = await API.post("/reports/pivot", body);
      setResult(data);
    } catch (e) {
      toast.error(apiErr(e));
    } finally { setLoading(false); }
  };

  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  const applyPreset = (p) => {
    const pf = { ...EMPTY_FILTERS, date_from: "", ...p.filters() };
    if (!("active" in p.filters())) pf.active = "true";
    setRow1(p.rows[0]); setRow2(p.rows[1] || ""); setCol(p.cols || "");
    setFilters(pf);
    run(p.rows, p.cols || null, pf);
  };

  // drill-down: build /leads params from row key (+ optional col key) + current report filters
  const drill = (rowKey, colKey = null, childKey = null) => {
    const params = {};
    const f = cleanFilters(filters);
    ["date_from", "date_to", "active", "user_id", "tags", "lead_stage", "source_lead",
      "campaign_name", "ads_platform", "state_name", "city", "follow_up_tag"].forEach((k) => {
      if (f[k]) params[k] = f[k];
    });
    Object.assign(params, dimFilterParams(result.row_dims[0], rowKey));
    if (childKey != null && result.row_dims[1]) Object.assign(params, dimFilterParams(result.row_dims[1], childKey));
    if (colKey != null && colKey !== "__count__" && result.col_dim) Object.assign(params, dimFilterParams(result.col_dim, colKey));
    navigate(leadsUrl(params));
  };

  const sortedRows = result ? [...result.rows].sort((a, b) => {
    const va = sortCol ? (a.cells[sortCol] || 0) : a.total;
    const vb = sortCol ? (b.cells[sortCol] || 0) : b.total;
    return sortDir * (va - vb);
  }) : [];

  const toggleSort = (ck) => {
    if (sortCol === ck) setSortDir((d) => -d);
    else { setSortCol(ck); setSortDir(-1); }
  };

  return (
    <>
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
        {/* dims */}
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
          <button data-testid="run-report-button" onClick={() => run()} className="hivf-btn-primary !py-2"><Play size={14} weight="fill" /> Run</button>
        </div>

        {/* full filter bar */}
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3">
          <Filter label="From"><input type="date" className="hivf-select block" value={filters.date_from} onChange={(e) => setF("date_from", e.target.value)} data-testid="pivot-date-from" /></Filter>
          <Filter label="To"><input type="date" className="hivf-select block" value={filters.date_to} onChange={(e) => setF("date_to", e.target.value)} data-testid="pivot-date-to" /></Filter>
          <Filter label="Status">
            <select className="hivf-select block" value={filters.active} onChange={(e) => setF("active", e.target.value)} data-testid="pivot-filter-active">
              <option value="true">Active</option><option value="false">Lost</option><option value="all">All</option>
            </select>
          </Filter>
          {user.role !== "caller" && (
            <Filter label="Caller">
              <select className="hivf-select block max-w-36" value={filters.user_id} onChange={(e) => setF("user_id", e.target.value)} data-testid="pivot-filter-caller">
                <option value="">All</option>
                {(catalogs?.users || []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </Filter>
          )}
          <Filter label="Tag">
            <select className="hivf-select block max-w-40" value={filters.tags} onChange={(e) => setF("tags", e.target.value)} data-testid="pivot-filter-tag">
              <option value="">All</option>
              {(catalogs?.tag || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Filter>
          <Filter label="Lead Stage">
            <select className="hivf-select block" value={filters.lead_stage} onChange={(e) => setF("lead_stage", e.target.value)} data-testid="pivot-filter-stage">
              <option value="">All</option>
              {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
          </Filter>
          <Filter label="Source">
            <select className="hivf-select block" value={filters.source_lead} onChange={(e) => setF("source_lead", e.target.value)} data-testid="pivot-filter-source">
              <option value="">All</option>
              {(catalogs?.source_lead || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
          </Filter>
          <Filter label="FU Tag">
            <select className="hivf-select block" value={filters.follow_up_tag} onChange={(e) => setF("follow_up_tag", e.target.value)} data-testid="pivot-filter-futag">
              <option value="">All</option>
              {(catalogs?.follow_up_tag || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
          </Filter>
          <Filter label="Ads Platform"><input className="hivf-select block !w-28" placeholder="e.g. meta" value={filters.ads_platform} onChange={(e) => setF("ads_platform", e.target.value)} data-testid="pivot-filter-adsplatform" /></Filter>
          <Filter label="Campaign"><input className="hivf-select block !w-32" placeholder="contains…" value={filters.campaign_name} onChange={(e) => setF("campaign_name", e.target.value)} data-testid="pivot-filter-campaign" /></Filter>
          <Filter label="State"><input className="hivf-select block !w-28" placeholder="contains…" value={filters.state_name} onChange={(e) => setF("state_name", e.target.value)} /></Filter>
          <Filter label="City"><input className="hivf-select block !w-28" placeholder="contains…" value={filters.city} onChange={(e) => setF("city", e.target.value)} /></Filter>
        </div>

        {loading ? <Spinner /> : !result ? null : result.rows.length === 0 ? (
          <EmptyState title="No data" subtitle="Try widening your date range" />
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm" data-testid="pivot-table">
              <thead>
                <tr className="border-b-2 border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
                  <th className="sticky left-0 bg-white py-2 pr-4">{DIMS.find(([v]) => v === result.row_dims[0])?.[1]}{result.row_dims[1] ? ` / ${DIMS.find(([v]) => v === result.row_dims[1])?.[1]}` : ""}</th>
                  {result.col_keys.map((c) => (
                    <th key={c.key} className="cursor-pointer select-none px-2 py-2 text-right hover:text-[#357ABD]"
                      onClick={() => toggleSort(c.key)} data-testid={`pivot-col-header-${c.key}`}>
                      {c.label}{sortCol === c.key && (sortDir === -1 ? <CaretDown size={10} className="ml-0.5 inline" /> : <CaretUp size={10} className="ml-0.5 inline" />)}
                    </th>
                  ))}
                  {result.col_keys.length > 1 && (
                    <th className="cursor-pointer select-none px-2 py-2 text-right font-extrabold hover:text-[#357ABD]" onClick={() => toggleSort(null)}>
                      Total{sortCol === null && (sortDir === -1 ? <CaretDown size={10} className="ml-0.5 inline" /> : <CaretUp size={10} className="ml-0.5 inline" />)}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r) => (
                  <React.Fragment key={r.key}>
                    <tr className="border-b border-slate-100 font-semibold hover:bg-[#4A90E2]/5">
                      <td className="sticky left-0 bg-white py-1.5 pr-4 text-slate-800">
                        <span className="inline-flex items-center gap-1">
                          {r.children?.length > 0 && (
                            <button onClick={() => setExpanded((e) => ({ ...e, [r.key]: !e[r.key] }))} className="text-slate-400" data-testid={`pivot-expand-${r.key}`}>
                              {expanded[r.key] ? <CaretDown size={12} /> : <CaretRight size={12} />}
                            </button>
                          )}
                          <button onClick={() => drill(r.key)} className="hover:text-[#357ABD] hover:underline" data-testid={`pivot-row-${r.key}`}>{r.label}</button>
                        </span>
                      </td>
                      {result.col_keys.map((c) => (
                        <td key={c.key} className="px-2 py-1.5 text-right">
                          {(r.cells[c.key] || 0) > 0 ? (
                            <button onClick={() => drill(r.key, c.key)} className="text-slate-600 hover:font-bold hover:text-[#357ABD] hover:underline">
                              {(r.cells[c.key] || 0).toLocaleString("en-IN")}
                            </button>
                          ) : <span className="text-slate-300">0</span>}
                        </td>
                      ))}
                      {result.col_keys.length > 1 && (
                        <td className="px-2 py-1.5 text-right">
                          <button onClick={() => drill(r.key)} className="font-extrabold text-slate-800 hover:text-[#357ABD] hover:underline">{r.total.toLocaleString("en-IN")}</button>
                        </td>
                      )}
                    </tr>
                    {expanded[r.key] && r.children?.map((ch) => (
                      <tr key={ch.key} className="border-b border-slate-50 bg-slate-50/50 text-slate-500">
                        <td className="sticky left-0 bg-slate-50 py-1 pl-6 pr-4">
                          <button onClick={() => drill(r.key, null, ch.key)} className="hover:text-[#357ABD] hover:underline">{ch.label}</button>
                        </td>
                        {result.col_keys.map((c) => (
                          <td key={c.key} className="px-2 py-1 text-right">
                            {(ch.cells[c.key] || 0) > 0 ? (
                              <button onClick={() => drill(r.key, c.key, ch.key)} className="hover:text-[#357ABD] hover:underline">{(ch.cells[c.key] || 0).toLocaleString("en-IN")}</button>
                            ) : <span className="text-slate-300">0</span>}
                          </td>
                        ))}
                        {result.col_keys.length > 1 && <td className="px-2 py-1 text-right font-bold">{ch.total.toLocaleString("en-IN")}</td>}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
                <tr className="border-t-2 border-slate-200 font-extrabold text-slate-900">
                  <td className="sticky left-0 bg-white py-2 pr-4">Total</td>
                  {result.col_keys.map((c) => <td key={c.key} className="px-2 py-2 text-right">{(result.col_totals[c.key] || 0).toLocaleString("en-IN")}</td>)}
                  {result.col_keys.length > 1 && <td className="px-2 py-2 text-right" data-testid="pivot-grand-total">{result.grand_total.toLocaleString("en-IN")}</td>}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function Filter({ label, children }) {
  return (
    <div>
      <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
