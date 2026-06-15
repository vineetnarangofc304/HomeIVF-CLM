import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PhoneIncoming, X, ArrowRight } from "@phosphor-icons/react";
import { API } from "../lib/api";

/**
 * Polls for the logged-in agent's live incoming Ozonetel call and shows a
 * floating screen-pop banner with the matched lead. Mounted globally in Layout.
 */
export default function IncomingCallBanner() {
  const navigate = useNavigate();
  const [call, setCall] = useState(null);
  const [lead, setLead] = useState(null);
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
      } catch (e) { /* ignore (e.g. logged out) */ }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!call) return null;

  const dismiss = () => {
    dismissedRef.current.add(call.ucid || call.id);
    setCall(null);
    setLead(null);
  };

  const open = () => {
    if (lead) navigate(`/leads/${lead.id}`);
    else navigate(`/leads?search=${encodeURIComponent(call.phone || "")}`);
    dismiss();
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
          <div className="mt-1">
            <p className="text-sm font-bold text-[#357ABD]" data-testid="banner-lead-name">{lead.contact_name || lead.name}</p>
            <p className="text-xs text-slate-500">Lead #{lead.id} · {lead.lead_stage || "No stage"}{lead.city ? ` · ${lead.city}` : ""}</p>
          </div>
        ) : (
          <p className="mt-1 text-xs text-slate-500">No matching lead — new caller</p>
        )}
        <button onClick={open} data-testid="banner-open-lead"
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-full bg-[#4A90E2] py-2 text-sm font-bold text-white transition-colors hover:bg-[#357ABD]">
          {lead ? "Open lead" : "Search caller"} <ArrowRight size={15} weight="bold" />
        </button>
      </div>
    </div>
  );
}
