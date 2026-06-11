import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { UsersThree, TrendUp, ClockCountdown, Warning, Trophy, Tag } from "@phosphor-icons/react";
import { API, leadsUrl, apiErr } from "../lib/api";
import { toast } from "sonner";
import { Spinner, StageBadge } from "../components/Bits";

function Kpi({ icon: Icon, label, value, tone = "blue", testid, onClick }) {
  const tones = {
    blue: "bg-[#4A90E2]/10 text-[#357ABD]",
    violet: "bg-[#8B5CF6]/10 text-[#8B5CF6]",
    green: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
  };
  return (
    <button onClick={onClick} data-testid={testid}
      className="hivf-card p-5 text-left transition-all hover:-translate-y-[2px] hover:border-[#4A90E2]/40 hover:shadow-md cursor-pointer">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl ${tones[tone]}`}>
        <Icon size={20} weight="duotone" />
      </div>
      <p className="font-display text-2xl font-extrabold text-slate-900">{value?.toLocaleString("en-IN") ?? "—"}</p>
      <p className="mt-0.5 text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
    </button>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    API.get("/reports/dashboard").then(({ data }) => setData(data)).catch((e) => { toast.error(apiErr(e)); setData({}); });
  }, []);

  if (!data) return <Spinner />;

  const chartData = (data.by_day || []).map((d) => ({ day: (d._id || "").slice(5), fullDay: d._id, count: d.count }));
  const today = data.today;
  const monthStart = data.month_start;

  return (
    <div className="space-y-6 p-6" data-testid="dashboard-page">
      <div>
        <h1 className="font-display text-2xl font-extrabold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Your lead engine at a glance — click any card or row to drill down</p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Kpi icon={UsersThree} label="Leads Today" value={data.leads_today} testid="kpi-leads-today"
          onClick={() => navigate(leadsUrl({ date_from: today }))} />
        <Kpi icon={UsersThree} label="Leads MTD" value={data.leads_mtd} tone="violet" testid="kpi-leads-mtd"
          onClick={() => navigate(leadsUrl({ date_from: monthStart }))} />
        <Kpi icon={TrendUp} label="Converted MTD" value={data.converted_mtd} tone="green" testid="kpi-converted-mtd"
          onClick={() => navigate(leadsUrl({ lead_stage: "Converted", date_from: monthStart }))} />
        <Kpi icon={ClockCountdown} label="Follow-ups Today" value={data.followups_today} tone="amber" testid="kpi-followups-today"
          onClick={() => navigate("/followups")} />
        <Kpi icon={Warning} label="Overdue Follow-ups" value={data.followups_overdue} tone="rose" testid="kpi-followups-overdue"
          onClick={() => navigate("/followups")} />
        <Kpi icon={UsersThree} label="Total Active Leads" value={data.total_leads} testid="kpi-total-leads"
          onClick={() => navigate("/leads")} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="hivf-card p-5 lg:col-span-2">
          <h3 className="font-display text-base font-bold text-slate-800">Incoming Leads — last 14 days <span className="text-xs font-normal text-slate-400">(click a bar)</span></h3>
          <div className="mt-4 h-64 min-h-64 w-full min-w-0">
            <ResponsiveContainer width="100%" height={256} minWidth={200}>
              <BarChart data={chartData} onClick={(e) => e?.activePayload?.[0] && navigate(leadsUrl({ date_from: e.activePayload[0].payload.fullDay, date_to: e.activePayload[0].payload.fullDay }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#64748b" }} />
                <YAxis tick={{ fontSize: 11, fill: "#64748b" }} width={40} />
                <Tooltip cursor={{ fill: "#f1f5f9" }} />
                <Bar dataKey="count" fill="#4A90E2" radius={[6, 6, 0, 0]} className="cursor-pointer" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="hivf-card p-5">
          <h3 className="font-display text-base font-bold text-slate-800">Funnel — Lead Stage</h3>
          <div className="mt-4 space-y-3" data-testid="funnel-by-stage">
            {(data.by_stage || []).map((s) => {
              const max = Math.max(...data.by_stage.map((x) => x.count), 1);
              return (
                <button key={String(s._id)} className="block w-full text-left"
                  data-testid={`funnel-stage-${String(s._id || "none").replace(/\s/g, "-")}`}
                  onClick={() => navigate(leadsUrl({ lead_stage: s._id || "__none__" }))}>
                  <div className="mb-1 flex items-center justify-between">
                    <StageBadge stage={s._id || "Undefined"} />
                    <span className="text-xs font-bold text-slate-600">{s.count.toLocaleString("en-IN")}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100 transition-all hover:h-2.5">
                    <div className="h-full rounded-full bg-gradient-to-r from-[#4A90E2] to-[#8B5CF6]"
                      style={{ width: `${Math.max((s.count / max) * 100, 2)}%` }} />
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="hivf-card p-5">
          <div className="flex items-center gap-2">
            <Trophy size={18} weight="duotone" className="text-amber-500" />
            <h3 className="font-display text-base font-bold text-slate-800">Caller Leaderboard — MTD</h3>
          </div>
          <table className="mt-3 w-full text-sm" data-testid="leaderboard-table">
            <thead>
              <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-2">Caller</th>
                <th className="py-2 text-right">Leads</th>
                <th className="py-2 text-right">Converted</th>
              </tr>
            </thead>
            <tbody>
              {(data.leaderboard || []).map((l, i) => (
                <tr key={i} data-testid={`leaderboard-row-${l._id}`}
                  onClick={() => l._id && navigate(leadsUrl({ user_id: l._id, date_from: monthStart }))}
                  className="cursor-pointer border-b border-slate-50 last:border-0 transition-colors hover:bg-[#4A90E2]/5">
                  <td className="py-2 font-semibold text-slate-700">{l.name}</td>
                  <td className="py-2 text-right text-slate-600">{l.count}</td>
                  <td className="py-2 text-right font-bold text-emerald-600">{l.converted}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="hivf-card p-5">
          <div className="flex items-center gap-2">
            <Tag size={18} weight="duotone" className="text-[#8B5CF6]" />
            <h3 className="font-display text-base font-bold text-slate-800">Top Dispositions — MTD</h3>
          </div>
          <div className="mt-4 space-y-2" data-testid="top-tags">
            {(data.top_tags || []).map((t) => {
              const max = Math.max(...data.top_tags.map((x) => x.count), 1);
              return (
                <button key={t._id} className="flex w-full items-center gap-3 text-left"
                  data-testid={`top-tag-${t._id}`}
                  onClick={() => navigate(leadsUrl({ tags: t._id, date_from: monthStart }))}>
                  <span className="w-44 truncate text-xs font-semibold text-slate-600 hover:text-[#357ABD]">{t.name}</span>
                  <div className="h-2 flex-1 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-[#8B5CF6]/70" style={{ width: `${Math.max((t.count / max) * 100, 2)}%` }} />
                  </div>
                  <span className="w-12 text-right text-xs font-bold text-slate-600">{t.count}</span>
                </button>
              );
            })}
          </div>
          <Link to="/reports" className="mt-4 inline-block text-xs font-bold text-[#357ABD] hover:underline">
            Open full reports →
          </Link>
        </div>
      </div>
    </div>
  );
}
