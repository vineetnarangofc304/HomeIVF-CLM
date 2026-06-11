import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CalendarCheck, CheckCircle, ChatCircleText } from "@phosphor-icons/react";
import { API, apiErr, fmtDay, todayStr } from "../lib/api";
import { useCatalogMaps } from "../context/AuthContext";
import { TagChip, StageBadge, Spinner, EmptyState } from "../components/Bits";

const TABS = [
  ["overdue", "Overdue", "text-rose-600"],
  ["today", "Due Today", "text-amber-600"],
  ["upcoming", "Upcoming", "text-[#357ABD]"],
];

export default function FollowUps() {
  const navigate = useNavigate();
  const { catalogs, tagById, userById } = useCatalogMaps();
  const [tab, setTab] = useState("today");
  const [leads, setLeads] = useState(null);
  const [activities, setActivities] = useState([]);
  const [counts, setCounts] = useState({});
  const [noteLead, setNoteLead] = useState(null);

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
      <p className="text-sm text-slate-500">Your recall queue — click a lead to open it, or log a quick note right here</p>

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
              <div key={a.id} onClick={() => navigate(`/leads/${a.lead_id}`)}
                className="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-100 p-2.5 transition-colors hover:bg-[#4A90E2]/5">
                <CalendarCheck size={17} className="text-[#4A90E2]" />
                <span className="flex-1 text-sm font-semibold text-slate-700">
                  {a.type_name}{a.summary ? ` — ${a.summary}` : ""} · <span className="text-slate-400">{a.lead_name}</span>
                </span>
                <span className="text-xs text-slate-500">{fmtDay(a.date_deadline)}</span>
                <button onClick={async (e) => { e.stopPropagation(); await API.post(`/activities/${a.id}/done`, {}); load(); }}
                  className="text-emerald-500" title="Mark done"><CheckCircle size={18} /></button>
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
                <th className="px-2 py-2.5">Quick Note</th>
              </tr>
            </thead>
            <tbody>
              {leads.items.map((l) => (
                <tr key={l.id} data-testid={`followup-row-${l.id}`} onClick={() => navigate(`/leads/${l.id}`)}
                  className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-[#4A90E2]/5">
                  <td className="px-4 py-2 font-semibold text-slate-800">{l.contact_name || l.name}</td>
                  <td className="px-2 py-2 text-slate-600">{l.phone || "—"}</td>
                  <td className={`px-2 py-2 font-bold ${tab === "overdue" ? "text-rose-500" : "text-slate-700"}`}>{fmtDay(l.follow_up_date)}</td>
                  <td className="px-2 py-2 text-slate-500">{l.follow_up_tag || "—"}</td>
                  <td className="px-2 py-2"><StageBadge stage={l.lead_stage} /></td>
                  <td className="px-2 py-2"><div className="flex max-w-48 flex-wrap gap-1">{(l.tags || []).slice(0, 2).map((t) => <TagChip key={t} tag={tagById[t]} />)}</div></td>
                  <td className="px-2 py-2 text-slate-500">{userById[l.user_id]?.name || "—"}</td>
                  <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                    <button data-testid={`quick-note-${l.id}`} onClick={() => setNoteLead(l)}
                      className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-xs font-bold text-[#357ABD] transition-colors hover:bg-[#4A90E2]/10">
                      <ChatCircleText size={13} /> Note
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {noteLead && (
        <QuickNoteModal lead={noteLead} catalogs={catalogs} onClose={() => setNoteLead(null)}
          onSaved={() => { setNoteLead(null); load(); }} />
      )}
    </div>
  );
}

function QuickNoteModal({ lead, catalogs, onClose, onSaved }) {
  const [note, setNote] = useState("");
  const [nextDate, setNextDate] = useState("");
  const [nextTag, setNextTag] = useState(lead.follow_up_tag || "");
  const [tagToAdd, setTagToAdd] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (note.trim()) {
        await API.post(`/leads/${lead.id}/messages`, { body: note.trim().replace(/\n/g, "<br/>"), subtype: "note" });
      }
      const updates = {};
      if (nextDate) updates.follow_up_date = nextDate;
      if (nextTag && nextTag !== lead.follow_up_tag) updates.follow_up_tag = nextTag;
      if (tagToAdd) updates.tags = [...new Set([...(lead.tags || []), parseInt(tagToAdd)])];
      if (Object.keys(updates).length) await API.patch(`/leads/${lead.id}`, { updates });
      toast.success("Follow-up logged");
      onSaved();
    } catch (err) {
      toast.error(apiErr(err));
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" data-testid="quick-note-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900">Quick Note — {lead.contact_name || lead.name}</h3>
        <p className="text-xs text-slate-500">{lead.phone} · follow-up {fmtDay(lead.follow_up_date)}</p>
        <div className="mt-4 space-y-3">
          <textarea data-testid="quick-note-input" autoFocus rows={3} className="hivf-input" placeholder="Call outcome / comments…" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Next follow-up</label>
              <input data-testid="quick-note-next-date" type="date" min={todayStr()} className="hivf-select mt-1 w-full" value={nextDate} onChange={(e) => setNextDate(e.target.value)} />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">FU Tag</label>
              <select className="hivf-select mt-1 w-full" value={nextTag} onChange={(e) => setNextTag(e.target.value)}>
                <option value="">—</option>
                {(catalogs?.follow_up_tag || []).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Add disposition tag</label>
            <select data-testid="quick-note-tag" className="hivf-select mt-1 w-full" value={tagToAdd} onChange={(e) => setTagToAdd(e.target.value)}>
              <option value="">None</option>
              {(catalogs?.tag || []).filter((t) => t.active !== false).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button data-testid="quick-note-submit" type="submit" disabled={saving} className="hivf-btn-primary">{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </div>
  );
}
