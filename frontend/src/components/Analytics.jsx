import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, PieChart, Pie, Cell,
} from "recharts";
import { API, leadsUrl, todayStr } from "../lib/api";
import { Spinner } from "./Bits";

const STAGE_COLORS = {
  "Contact Attempt": "#f59e0b", Contacted: "#4A90E2", Converted: "#10b981",
  Closed: "#94a3b8", Undefined: "#c4b5fd",
};
const PIE_COLORS = ["#4A90E2", "#8B5CF6", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#a855f7", "#84cc16"];
const DOW_LABELS = { 1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat" };

export default function Analytics() {
  const navigate = useNavigate();
  const [granularity, setGranularity] = useState("day");
  const [trends, setTrends] = useState(null);
  const [dowHour, setDowHour] = useState(null);
  const [callerDay, setCallerDay] = useState(null);
  const [sources, setSources] = useState(null);

  useEffect(() => {
    setTrends(null);
    API.get("/reports/trends", { params: { granularity } }).then(({ data }) => setTrends(data));
  }, [granularity]);

  useEffect(() => {
    API.get("/reports/heatmap", { params: { type: "dow_hour" } }).then(({ data }) => setDowHour(data));
    API.get("/reports/heatmap", { params: { type: "caller_day" } }).then(({ data }) => setCallerDay(data));
    API.post("/reports/pivot", { rows: ["source_lead"], cols: null, filters: { active: "all", date_from: todayStr().slice(0, 7) + "-01" } })
      .then(({ data }) => setSources(data));
  }, []);

  const stages = trends?.stages || [];
  const series = (trends?.series || []).map((s) => ({ ...s }));
  const convSeries = series.map((s) => ({
    period: s.period,
    converted: s.Converted || 0,
    rate: s.total ? Math.round(((s.Converted || 0) / s.total) * 1000) / 10 : 0,
  }));

  return (
    <div className="mt-5 space-y-5" data-testid="analytics-section">
      {/* Trend: stacked by stage */}
      <div className="hivf-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-display text-base font-bold text-slate-800">Lead Volume Trend — by Lead Stage</h3>
          <div className="flex overflow-hidden rounded-full border border-slate-200">
            {["day", "week", "month"].map((g) => (
              <button key={g} data-testid={`trend-granularity-${g}`} onClick={() => setGranularity(g)}
                className={`px-3 py-1.5 text-xs font-bold capitalize ${granularity === g ? "bg-[#4A90E2] text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}>
                {g}
              </button>
            ))}
          </div>
        </div>
        {!trends ? <Spinner /> : (
          <div className="mt-4 h-72 w-full min-w-0">
            <ResponsiveContainer width="100%" height={288} minWidth={200}>
              <AreaChart data={series}
                onClick={(e) => {
                  const p = e?.activePayload?.[0]?.payload?.period;
                  if (!p) return;
                  if (granularity === "month") navigate(leadsUrl({ date_from: `${p}-01`, date_to: `${p}-31`, active: "all" }));
                  else navigate(leadsUrl({ date_from: p, date_to: granularity === "week" ? undefined : p, active: "all" }));
                }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11, fill: "#64748b" }} width={42} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {stages.map((s) => (
                  <Area key={s} type="monotone" dataKey={s} stackId="1" stroke={STAGE_COLORS[s] || "#8B5CF6"}
                    fill={STAGE_COLORS[s] || "#8B5CF6"} fillOpacity={0.55} className="cursor-pointer" />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Conversion trend */}
        <div className="hivf-card p-5">
          <h3 className="font-display text-base font-bold text-slate-800">Conversions & Conversion Rate</h3>
          {!trends ? <Spinner /> : (
            <div className="mt-4 h-64 w-full min-w-0">
              <ResponsiveContainer width="100%" height={256} minWidth={200}>
                <LineChart data={convSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis yAxisId="l" tick={{ fontSize: 11, fill: "#64748b" }} width={36} />
                  <YAxis yAxisId="r" orientation="right" unit="%" tick={{ fontSize: 11, fill: "#10b981" }} width={42} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line yAxisId="l" type="monotone" dataKey="converted" name="Converted" stroke="#10b981" strokeWidth={2} dot={false} />
                  <Line yAxisId="r" type="monotone" dataKey="rate" name="Conv. rate %" stroke="#8B5CF6" strokeWidth={2} strokeDasharray="4 3" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Source donut */}
        <div className="hivf-card p-5">
          <h3 className="font-display text-base font-bold text-slate-800">Lead Sources — this month <span className="text-xs font-normal text-slate-400">(click a slice)</span></h3>
          {!sources ? <Spinner /> : (
            <div className="mt-4 h-64 w-full min-w-0">
              <ResponsiveContainer width="100%" height={256} minWidth={200}>
                <PieChart>
                  <Pie data={sources.rows.map((r) => ({ name: r.label, value: r.total, key: r.key }))}
                    dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}
                    onClick={(d) => d?.key && d.key !== "__null__" && navigate(leadsUrl({ source_lead: d.key, date_from: todayStr().slice(0, 7) + "-01", active: "all" }))}>
                    {sources.rows.map((r, i) => <Cell key={r.key} fill={PIE_COLORS[i % PIE_COLORS.length]} className="cursor-pointer" />)}
                  </Pie>
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* DOW x Hour heatmap */}
      <div className="hivf-card p-5">
        <h3 className="font-display text-base font-bold text-slate-800">Incoming Lead Heatmap — Day of Week × Hour <span className="text-xs font-normal text-slate-400">(last 90 days, IST)</span></h3>
        {!dowHour ? <Spinner /> : <DowHourGrid cells={dowHour.cells} />}
      </div>

      {/* Caller x Day heatmap */}
      <div className="hivf-card p-5">
        <h3 className="font-display text-base font-bold text-slate-800">Caller Load Heatmap — last 14 days <span className="text-xs font-normal text-slate-400">(click a cell to open those leads)</span></h3>
        {!callerDay ? <Spinner /> : <CallerDayGrid cells={callerDay.cells} navigate={navigate} />}
      </div>
    </div>
  );
}

function heatColor(v, max) {
  if (!v) return "#f8fafc";
  const t = Math.min(v / max, 1);
  // blue -> violet ramp
  const a = 0.12 + t * 0.88;
  return `rgba(74, 144, 226, ${a})`;
}

function DowHourGrid({ cells }) {
  const map = {};
  let max = 1;
  cells.forEach((c) => { map[`${c.dow}-${c.hour}`] = c.count; max = Math.max(max, c.count); });
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const dows = [2, 3, 4, 5, 6, 7, 1]; // Mon..Sun
  return (
    <div className="mt-4 overflow-x-auto" data-testid="dow-hour-heatmap">
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th />
            {hours.map((h) => <th key={h} className="px-0.5 text-[9px] font-semibold text-slate-400">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {dows.map((d) => (
            <tr key={d}>
              <td className="pr-2 text-[10px] font-bold text-slate-500">{DOW_LABELS[d]}</td>
              {hours.map((h) => {
                const v = map[`${d}-${h}`] || 0;
                return (
                  <td key={h} title={`${DOW_LABELS[d]} ${h}:00 — ${v} leads`}
                    className="h-6 w-7 rounded-md text-center text-[9px] font-semibold"
                    style={{ background: heatColor(v, max), color: v / max > 0.55 ? "white" : "#64748b" }}>
                    {v || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CallerDayGrid({ cells, navigate }) {
  const days = [...new Set(cells.map((c) => c.day))].sort();
  const users = {};
  let max = 1;
  cells.forEach((c) => {
    const key = c.user || "Unassigned";
    users[key] = users[key] || { user_id: c.user_id, days: {}, total: 0 };
    users[key].days[c.day] = c.count;
    users[key].total += c.count;
    max = Math.max(max, c.count);
  });
  const sorted = Object.entries(users).sort((a, b) => b[1].total - a[1].total).slice(0, 30);
  return (
    <div className="mt-4 overflow-x-auto" data-testid="caller-day-heatmap">
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th className="text-left text-[10px] font-semibold text-slate-400">Caller</th>
            {days.map((d) => <th key={d} className="px-1 text-[9px] font-semibold text-slate-400">{d.slice(5)}</th>)}
            <th className="px-2 text-[10px] font-bold text-slate-500">Total</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(([name, u]) => (
            <tr key={name}>
              <td className="max-w-32 truncate pr-2 text-[11px] font-bold text-slate-600">{name}</td>
              {days.map((d) => {
                const v = u.days[d] || 0;
                return (
                  <td key={d} title={`${name} · ${d} — ${v} leads`}
                    onClick={() => v && u.user_id && navigate(leadsUrl({ user_id: u.user_id, date_from: d, date_to: d, active: "all" }))}
                    className={`h-6 w-10 rounded-md text-center text-[9px] font-semibold ${v ? "cursor-pointer hover:ring-1 hover:ring-[#4A90E2]" : ""}`}
                    style={{ background: heatColor(v, max), color: v / max > 0.55 ? "white" : "#64748b" }}>
                    {v || ""}
                  </td>
                );
              })}
              <td className="px-2 text-right text-[11px] font-extrabold text-slate-700">{u.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
