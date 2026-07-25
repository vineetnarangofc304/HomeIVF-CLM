import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { BellRinging, X, CheckCircle } from "@phosphor-icons/react";
import { API, fmtDay } from "../lib/api";
import { usePoll } from "../hooks/usePoll";

// Case 2 — owner-only follow-up reminder. Backend returns a reminder ONLY to the
// follow-up's creator, and ONLY in the 5-minute window before the scheduled time
// (never after). Shows once per follow-up (dismissals persist for the day). Anchored
// bottom-RIGHT so it never covers the left side menu.
export default function FollowUpReminder() {
  const navigate = useNavigate();
  const [reminders, setReminders] = useState([]);
  const lsKey = `fu_dismissed_${new Date().toISOString().slice(0, 10)}`;
  const dismissed = useRef(new Set(JSON.parse(localStorage.getItem(lsKey) || "[]")));

  const persist = () => {
    try { localStorage.setItem(lsKey, JSON.stringify([...dismissed.current])); } catch { /* ignore */ }
  };

  const load = async () => {
    try {
      const { data } = await API.get("/leads/followups/reminders", { noCancel: true });
      const active = (data.reminders || []).filter((r) => !dismissed.current.has(r.follow_up_id));
      setReminders(active);
    } catch { /* silent — reminders are best-effort */ }
  };

  usePoll(load, 60000, "fu-reminders");

  const dismiss = (id) => {
    dismissed.current.add(id);
    persist();
    setReminders((rs) => rs.filter((r) => r.follow_up_id !== id));
  };

  const markDone = async (r) => {
    try {
      await API.post(`/leads/${r.lead_id}/followups/${r.follow_up_id}/status`, { status: "Completed" });
      toast.success("Follow-up marked completed");
    } catch { /* still dismiss */ }
    dismiss(r.follow_up_id);
  };

  if (reminders.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] w-80 space-y-2" data-testid="followup-reminder-stack">
      {reminders.map((r) => (
        <div key={r.follow_up_id} data-testid={`followup-reminder-${r.follow_up_id}`}
          className="animate-in slide-in-from-right-2 rounded-2xl border border-amber-200 bg-white p-4 shadow-xl ring-1 ring-amber-100">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 rounded-full bg-amber-100 p-1.5 text-amber-600"><BellRinging size={16} weight="fill" /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-bold uppercase tracking-wider text-amber-600">Follow-up reminder</p>
              <button onClick={() => { dismiss(r.follow_up_id); navigate(`/leads/${r.lead_id}`); }}
                className="block truncate text-sm font-extrabold text-slate-800 hover:underline" data-testid={`followup-reminder-name-${r.follow_up_id}`}>
                {r.lead_name}
              </button>
              <p className="text-xs font-semibold text-slate-600">{fmtDay(r.follow_up_date)} · {r.follow_up_time}{r.phone ? ` · ${r.phone}` : ""}</p>
              {r.note && <p className="mt-1 text-xs text-slate-500 line-clamp-3">{r.note}</p>}
              <div className="mt-2 flex gap-2">
                <button onClick={() => markDone(r)} data-testid={`followup-reminder-done-${r.follow_up_id}`}
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-500 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-emerald-600"><CheckCircle size={13} /> Mark done</button>
                <button onClick={() => { dismiss(r.follow_up_id); navigate(`/leads/${r.lead_id}`); }}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-[11px] font-bold text-[#357ABD] hover:bg-[#4A90E2]/10">Open lead</button>
              </div>
            </div>
            <button onClick={() => dismiss(r.follow_up_id)} className="text-slate-300 hover:text-slate-500" data-testid={`followup-reminder-dismiss-${r.follow_up_id}`} title="Dismiss"><X size={15} /></button>
          </div>
        </div>
      ))}
    </div>
  );
}
