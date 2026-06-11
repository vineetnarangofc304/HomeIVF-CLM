import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarCheck, CheckCircle } from "@phosphor-icons/react";
import { API, fmtDay } from "../lib/api";
import { useCatalogMaps } from "../context/AuthContext";
import { TagChip, StageBadge, Spinner, EmptyState } from "../components/Bits";

const TABS = [
  ["overdue", "Overdue", "text-rose-600"],
  ["today", "Due Today", "text-amber-600"],
  ["upcoming", "Upcoming", "text-[#357ABD]"],
];

export default function FollowUps() {
  const { tagById, userById } = useCatalogMaps();
  const [tab, setTab] = useState("today");
  const [leads, setLeads] = useState(null);
  const [activities, setActivities] = useState([]);
  const [counts, setCounts] = useState({});

  const load = useCallback(async () => {
    setLeads(null);
    const [{ data: l }, { data: a }] = await Promise.all([
      API.get("/leads", { params: { follow_up: tab, limit: 100, sort: "follow_up_date", order: "asc" } }),
      API.get("/activities", { params: { when: tab === "upcoming" ? "upcoming" : tab, scope: "my" } }),
    ]);
    setLeads(l);
    setActivities(a.items);
  }, [tab]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    (async () => {
      const res = {};
      for (const [k] of TABS) {
        const { data } = await API.get("/leads", { params: { follow_up: k, limit: 1 } });
        res[k] = data.total;
      }
      setCounts(res);
    })();
  }, []);

  return (
    <div className="p-6" data-testid="followups-page">
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Follow-ups</h1>
      <p className="text-sm text-slate-500">Your recall queue — never miss a callback</p>

      <div className="mt-5 flex gap-2">
        {TABS.map(([k, label, color]) => (
          <button key={k} data-testid={`followup-tab-${k}`} onClick={() => setTab(k)}
            className={`rounded-full border px-4 py-2 text-sm font-bold transition-colors ${tab === k ? "border-[#4A90E2] bg-[#4A90E2]/10 " + color : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"}`}>
            {label} {counts[k] != null && <span className="ml-1 rounded-full bg-white px-1.5 text-xs">{counts[k]}</span>}
          </button>
        ))}
      </div>

      {activities.length > 0 && (
        <div className="mt-5 hivf-card p-4">
          <h3 className="mb-2 font-display text-sm font-extrabold text-slate-800">My Scheduled Activities</h3>
          <div className="space-y-2" data-testid="followup-activities">
            {activities.map((a) => (
              <div key={a.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-2.5">
                <CalendarCheck size={17} className="text-[#4A90E2]" />
                <Link to={`/leads/${a.lead_id}`} className="flex-1 text-sm font-semibold text-slate-700 hover:text-[#357ABD]">
                  {a.type_name}{a.summary ? ` — ${a.summary}` : ""} · <span className="text-slate-400">{a.lead_name}</span>
                </Link>
                <span className="text-xs text-slate-500">{fmtDay(a.date_deadline)}</span>
                <button onClick={async () => { await API.post(`/activities/${a.id}/done`, {}); load(); }} className="text-emerald-500"><CheckCircle size={18} /></button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-5 hivf-card overflow-hidden">
        {!leads ? <Spinner /> : leads.items.length === 0 ? (
          <EmptyState title="Nothing here" subtitle="No leads with follow-ups in this bucket" />
        ) : (
          <table className="w-full text-sm" data-testid="followups-table">
            <thead className="bg-slate-50">
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="px-4 py-2.5">Lead</th>
                <th className="px-2 py-2.5">Phone</th>
                <th className="px-2 py-2.5">Follow-up</th>
                <th className="px-2 py-2.5">FU Tag</th>
                <th className="px-2 py-2.5">Stage</th>
                <th className="px-2 py-2.5">Tags</th>
                <th className="px-2 py-2.5">Caller</th>
              </tr>
            </thead>
            <tbody>
              {leads.items.map((l) => (
                <tr key={l.id} className="border-b border-slate-100 transition-colors hover:bg-[#4A90E2]/5">
                  <td className="px-4 py-2">
                    <Link to={`/leads/${l.id}`} className="font-semibold text-slate-800 hover:text-[#357ABD]">{l.contact_name || l.name}</Link>
                  </td>
                  <td className="px-2 py-2 text-slate-600">{l.phone || "—"}</td>
                  <td className={`px-2 py-2 font-bold ${tab === "overdue" ? "text-rose-500" : "text-slate-700"}`}>{fmtDay(l.follow_up_date)}</td>
                  <td className="px-2 py-2 text-slate-500">{l.follow_up_tag || "—"}</td>
                  <td className="px-2 py-2"><StageBadge stage={l.lead_stage} /></td>
                  <td className="px-2 py-2"><div className="flex max-w-48 flex-wrap gap-1">{(l.tags || []).slice(0, 2).map((t) => <TagChip key={t} tag={tagById[t]} />)}</div></td>
                  <td className="px-2 py-2 text-slate-500">{userById[l.user_id]?.name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
