import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PhoneIncoming, PhoneOutgoing, PhoneX, ArrowsClockwise } from "@phosphor-icons/react";
import { API, fmtDate } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const fmtSecs = (s) => {
  s = parseInt(s || 0, 10);
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m}m ${r}s` : `${r}s`;
};
const STATUS_BADGE = {
  connected: "bg-emerald-50 text-emerald-600", missed: "bg-rose-50 text-rose-600",
  not_connected: "bg-amber-50 text-amber-600", queued: "bg-slate-100 text-slate-500",
  failed: "bg-rose-50 text-rose-600",
};

export default function CallCenter() {
  const { user } = useAuth();
  const isMgr = user.role === "admin" || user.role === "manager";
  const TABS = ["Call Logs", "Missed Calls", ...(isMgr ? ["Agent Live Status", "Break Reports"] : [])];
  const [tab, setTab] = useState("Call Logs");

  return (
    <div className="p-6" data-testid="call-center-page">
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Call Center</h1>
      <p className="mt-1 text-sm text-slate-500">Ozonetel calls, agent availability and break tracking.</p>
      <div className="mt-4 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} data-testid={`cc-tab-${t.replace(/\s+/g, "-").toLowerCase()}`}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-bold transition-colors ${tab === t ? "border-[#4A90E2] text-[#357ABD]" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {(tab === "Call Logs" || tab === "Missed Calls") && <CallList status={tab === "Missed Calls" ? "missed" : null} />}
        {tab === "Agent Live Status" && <AgentLive />}
        {tab === "Break Reports" && <BreakReports />}
      </div>
    </div>
  );
}

function CallList({ status }) {
  const [data, setData] = useState(null);
  const load = () => API.get("/calls", { params: { limit: 100, ...(status ? { status } : {}) } }).then(({ data }) => setData(data));
  useEffect(() => { load(); }, [status]);
  if (!data) return <Spinner />;
  if (data.items.length === 0) return <Empty msg={status === "missed" ? "No missed calls 🎉" : "No calls logged yet."} />;
  return (
    <div className="hivf-card overflow-hidden">
      <table className="w-full text-sm" data-testid="call-list-table">
        <thead><tr className="border-b border-slate-100 bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-400">
          <th className="px-3 py-2">Type</th><th className="px-3 py-2">Number</th><th className="px-3 py-2">Lead</th>
          <th className="px-3 py-2">Agent</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Duration</th>
          <th className="px-3 py-2">Disposition</th><th className="px-3 py-2">Recording</th><th className="px-3 py-2">When</th></tr></thead>
        <tbody>
          {data.items.map((c) => (
            <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50/50" data-testid={`call-list-row-${c.id}`}>
              <td className="px-3 py-2">
                {c.direction === "incoming" ? (c.status === "missed" ? <PhoneX size={16} className="text-rose-500" /> : <PhoneIncoming size={16} className="text-emerald-500" />) : <PhoneOutgoing size={16} className="text-indigo-500" />}
              </td>
              <td className="px-3 py-2 font-semibold text-slate-700">{c.phone || "—"}</td>
              <td className="px-3 py-2">{c.lead_id ? <Link className="font-semibold text-[#357ABD]" to={`/leads/${c.lead_id}`}>{c.lead_name || `#${c.lead_id}`}</Link> : <span className="text-slate-400">—</span>}</td>
              <td className="px-3 py-2 text-slate-500">{c.agent_name || c.agent_phone_name || "—"}</td>
              <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATUS_BADGE[c.status] || "bg-slate-100 text-slate-500"}`}>{c.status || c.direction}</span></td>
              <td className="px-3 py-2 text-slate-500">{c.duration || "—"}</td>
              <td className="px-3 py-2 text-slate-500">{c.disposition || "—"}</td>
              <td className="px-3 py-2">{c.recording_url ? <audio controls preload="none" src={c.recording_url} className="h-7 w-40" /> : <span className="text-slate-300">—</span>}</td>
              <td className="px-3 py-2 text-xs text-slate-400">{fmtDate(c.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AgentLive() {
  const [agents, setAgents] = useState(null);
  const load = () => API.get("/agent/live").then(({ data }) => setAgents(data));
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  if (!agents) return <Spinner />;
  const dot = { "Available": "bg-emerald-500", "On Call": "bg-indigo-500", "Offline": "bg-slate-300" };
  return (
    <div>
      <div className="mb-3 flex justify-end"><button onClick={load} className="hivf-btn-secondary !py-1.5 text-xs" data-testid="agent-live-refresh"><ArrowsClockwise size={14} /> Refresh</button></div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="agent-live-grid">
        {agents.map((a) => (
          <div key={a.id} className="hivf-card flex items-center gap-3 p-3" data-testid={`agent-live-${a.id}`}>
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#4A90E2]/15 font-display text-sm font-extrabold text-[#357ABD]">{a.name?.[0]?.toUpperCase()}</div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold text-slate-800">{a.name}</p>
              <p className="flex items-center gap-1.5 text-xs text-slate-500">
                <span className={`h-2 w-2 rounded-full ${dot[a.status] || "bg-amber-500"}`} />{a.status}
                {a.since_seconds ? ` · ${fmtSecs(a.since_seconds)}` : ""}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-400">Break today</p>
              <p className="text-sm font-bold text-amber-600">{fmtSecs(a.break_seconds_today)}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function BreakReports() {
  const [logs, setLogs] = useState(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const load = () => API.get("/agent/status-logs", { params: { date, breaks_only: true } }).then(({ data }) => setLogs(data));
  useEffect(() => { load(); }, [date]);
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <label className="text-xs font-bold text-slate-500">Date</label>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="hivf-input !w-44 !py-1.5 text-sm" data-testid="break-report-date" />
      </div>
      {!logs ? <Spinner /> : logs.length === 0 ? <Empty msg="No breaks logged for this date." /> : (
        <div className="hivf-card overflow-hidden">
          <table className="w-full text-sm" data-testid="break-report-table">
            <thead><tr className="border-b border-slate-100 bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-3 py-2">Agent</th><th className="px-3 py-2">Break type</th><th className="px-3 py-2">Start</th><th className="px-3 py-2">End</th><th className="px-3 py-2">Duration</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-slate-50" data-testid={`break-row-${l.id}`}>
                  <td className="px-3 py-2 font-semibold text-slate-700">{l.user_name}</td>
                  <td className="px-3 py-2 text-slate-600">{l.status}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">{fmtDate(l.start)}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">{l.end ? fmtDate(l.end) : <span className="text-amber-600">ongoing</span>}</td>
                  <td className="px-3 py-2 font-bold text-amber-600">{fmtSecs(l.duration_sec)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const Spinner = () => <div className="flex justify-center py-12"><div className="h-7 w-7 animate-spin rounded-full border-2 border-[#4A90E2] border-t-transparent" /></div>;
const Empty = ({ msg }) => <div className="hivf-card p-10 text-center text-sm text-slate-400">{msg}</div>;
