import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PhoneIncoming, ArrowSquareOut, UserCircle, MapPin } from "@phosphor-icons/react";
import { API } from "../lib/api";

/**
 * Ozonetel Screen-Pop page. Configure this URL in Ozonetel (Admin → Settings →
 * Screen Pop URL). Ozonetel opens it (iframe / popup / new tab) on each incoming
 * call, appending params like ?phoneNumber=&ucid=&agentID=&phoneName=...
 * We record the call and show the matched lead to the agent.
 */
export default function ScreenPop() {
  const [sp] = useSearchParams();
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    const params = {};
    sp.forEach((v, k) => (params[k] = v));
    API.post("/calls/ozonetel/screenpop", params)
      .then(({ data }) => setState({ loading: false, ...data }))
      .catch(() => setState({ loading: false, error: true }));
  }, [sp]);

  const phone = sp.get("phoneNumber") || sp.get("callerID") || sp.get("customer") || "";
  const crmBase = window.location.origin;

  return (
    <div className="min-h-screen bg-slate-50 p-4" data-testid="screen-pop">
      <div className="mx-auto max-w-md">
        <div className="flex items-center gap-2 rounded-t-2xl bg-gradient-to-r from-[#4A90E2] to-[#8B5CF6] px-4 py-3 text-white">
          <PhoneIncoming size={20} weight="fill" className="animate-pulse" />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-white/80">Incoming call</p>
            <p className="font-display text-lg font-extrabold leading-tight" data-testid="screen-pop-phone">{phone || "Unknown"}</p>
          </div>
        </div>

        <div className="rounded-b-2xl border border-t-0 border-slate-200 bg-white p-4">
          {state.loading && <p className="py-6 text-center text-sm text-slate-400" data-testid="screen-pop-loading">Looking up caller…</p>}

          {!state.loading && state.error && (
            <p className="py-6 text-center text-sm text-rose-500" data-testid="screen-pop-error">Could not reach CRM. Check the Screen-Pop URL.</p>
          )}

          {!state.loading && !state.error && state.matched && state.lead && (
            <div data-testid="screen-pop-matched">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#4A90E2]/15 font-display text-lg font-extrabold text-[#357ABD]">
                  {(state.lead.contact_name || state.lead.name || "?")[0]?.toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-display text-base font-extrabold text-slate-900" data-testid="screen-pop-lead-name">
                    {state.lead.contact_name || state.lead.name}
                  </p>
                  <p className="text-xs text-slate-500">Lead #{state.lead.id} · {state.lead.lead_stage || "No stage"}</p>
                </div>
              </div>
              <div className="mt-3 space-y-1.5 text-sm text-slate-600">
                {(state.lead.city || state.lead.state_name) && (
                  <p className="flex items-center gap-2"><MapPin size={15} className="text-slate-400" />{[state.lead.city, state.lead.state_name].filter(Boolean).join(", ")}</p>
                )}
                {state.lead.email_from && <p className="truncate text-slate-500">{state.lead.email_from}</p>}
                {state.lead.source_lead && <p className="text-xs text-slate-400">Source: {state.lead.source_lead}</p>}
              </div>
              <a href={`${crmBase}/leads/${state.lead.id}`} target="_blank" rel="noreferrer"
                data-testid="screen-pop-open-lead"
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-full bg-[#4A90E2] py-2.5 text-sm font-bold text-white transition-colors hover:bg-[#357ABD]">
                <ArrowSquareOut size={16} weight="bold" /> Open full lead in CRM
              </a>
            </div>
          )}

          {!state.loading && !state.error && !state.matched && (
            <div className="py-2 text-center" data-testid="screen-pop-no-match">
              <UserCircle size={40} weight="thin" className="mx-auto text-slate-300" />
              <p className="mt-2 text-sm font-bold text-slate-700">New caller</p>
              <p className="text-xs text-slate-500">No existing lead matches this number.</p>
              <a href={`${crmBase}/leads?search=${encodeURIComponent(phone)}`} target="_blank" rel="noreferrer"
                className="mt-4 inline-flex items-center justify-center gap-2 rounded-full border border-[#4A90E2] px-4 py-2 text-sm font-bold text-[#357ABD] transition-colors hover:bg-[#4A90E2]/10">
                <ArrowSquareOut size={15} weight="bold" /> Search in CRM
              </a>
            </div>
          )}
        </div>
        <p className="mt-3 text-center text-[10px] uppercase tracking-[0.2em] text-slate-400">HomeIVF CRM · Powered by TifTech</p>
      </div>
    </div>
  );
}
