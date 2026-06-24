import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PhoneIncoming, X, ArrowRight } from "@phosphor-icons/react";
import { toast } from "sonner";
import { API, apiErr } from "../lib/api";

const DISPOSITIONS = ["Interested", "Not interested", "Call back later", "Converted"];

/**
 * Polls for the logged-in agent's live incoming Ozonetel call and shows a
 * floating screen-pop with the matched lead + disposition logging (§4).
 */
export default function IncomingCallBanner() {
  const navigate = useNavigate();
  const [call, setCall] = useState(null);
  const [lead, setLead] = useState(null);
  const [disp, setDisp] = useState("");
  const [note, setNote] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [saving, setSaving] = useState(false);
  const dismissedRef = useRef(new Set());

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { data } = await API.get("/calls/active");
        if (!alive) return;
        const c = data.active;
        if (c && !dismissedRef.current.has(c.ucid || c.id)) {
          setCall(c);
          setLead(data.lead || null);
        }
      } catch (e) { /* logged out */ }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!call) return null;

  const reset = () => { setDisp(""); setNote(""); setFollowUp(""); };
  const dismiss = () => {
    dismissedRef.current.add(call.ucid || call.id);
    setCall(null); setLead(null); reset();
  };
  const open = () => {
    if (lead) navigate(`/leads/${lead.id}`);
    else navigate(`/leads?search=${encodeURIComponent(call.phone || "")}`);
  };

  const saveDisposition = async () => {
    setSaving(true);
    try {
      await API.post(`/calls/${call.id}/disposition`, {
        disposition: disp, note: note || null,
        follow_up_date: disp === "Call back later" ? (followUp || null) : null,
      });
      toast.success(`Logged: ${disp}`);
      dismiss();
    } catch (e) { toast.error(apiErr(e)); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed right-5 top-5 z-[100] w-80 animate-[slideIn_0.3s_ease-out] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl" data-testid="incoming-call-banner">
      <div className="flex items-center gap-2 bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2.5 text-white">
        <PhoneIncoming size={18} weight="fill" className="animate-pulse" />
        <span className="text-xs font-bold uppercase tracking-[0.18em]">Incoming call</span>
        <button onClick={dismiss} data-testid="dismiss-call-banner" className="ml-auto rounded-full p-1 text-white/80 hover:bg-white/20 hover:text-white"><X size={15} /></button>
      </div>
      <div className="p-4">
        <p className="font-display text-lg font-extrabold text-slate-900" data-testid="banner-phone">{call.phone || "Unknown number"}</p>
        {lead ? (
          <button onClick={open} className="mt-0.5 text-left" data-testid="banner-open-lead">
            <p className="text-sm font-bold text-[#357ABD]" data-testid="banner-lead-name">{lead.contact_name || lead.name}</p>
            <p className="text-xs text-slate-500">Lead #{lead.id} · {lead.lead_stage || "No stage"}{lead.city ? ` · ${lead.city}` : ""}</p>
          </button>
        ) : (
          <p className="mt-1 text-xs text-slate-500">No matching lead — new caller</p>
        )}

        <div className="mt-3 border-t border-slate-100 pt-3">
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">Log outcome</p>
          <div className="grid grid-cols-2 gap-1.5">
            {DISPOSITIONS.map((d) => (
              <button key={d} onClick={() => setDisp(d)} data-testid={`disposition-${d.replace(/\s+/g, "-").toLowerCase()}`}
                className={`rounded-lg px-2 py-1.5 text-[11px] font-bold transition-colors ${disp === d ? "bg-[#4A90E2] text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                {d}
              </button>
            ))}
          </div>
          {disp && (
            <div className="mt-2 space-y-2" data-testid="disposition-detail">
              {disp === "Call back later" && (
                <input type="datetime-local" value={followUp} onChange={(e) => setFollowUp(e.target.value)}
                  className="hivf-input !py-1.5 text-xs" data-testid="disposition-followup" />
              )}
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Notes (optional)…"
                className="hivf-input !py-1.5 text-xs" data-testid="disposition-note" />
              <button onClick={saveDisposition} disabled={saving} data-testid="disposition-save"
                className="flex w-full items-center justify-center gap-2 rounded-full bg-emerald-500 py-2 text-sm font-bold text-white hover:bg-emerald-600 disabled:opacity-60">
                {saving ? "Saving…" : "Save outcome"} <ArrowRight size={15} weight="bold" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
