import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Check } from "@phosphor-icons/react";
import { API } from "../lib/api";
import { Spinner } from "../components/Bits";
import { WA_STATUS_FLOW, waMeta } from "../lib/waStatus";

const fmt = (s) => {
  if (!s) return "—";
  try { return new Date(s.replace(" ", "T") + "Z").toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch { return s; }
};

export default function WaMessageDetail() {
  const { trackId } = useParams();
  const navigate = useNavigate();
  const [m, setM] = useState(null);

  useEffect(() => { API.get(`/wa/message/${trackId}`).then(({ data }) => setM(data)); }, [trackId]);
  if (!m) return <Spinner />;

  const reached = new Set((m.status_history || []).map((h) => h.status));
  reached.add(m.status);
  const meta = waMeta(m.status);

  return (
    <div className="p-6" data-testid="wa-message-detail">
      <button onClick={() => navigate(-1)} className="mb-3 inline-flex items-center gap-1 text-sm font-bold text-slate-400 hover:text-slate-600"><ArrowLeft size={15} /> Back</button>
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Message Detail</h1>

      {/* Lifecycle tracker */}
      <div className="hivf-card mt-4 overflow-x-auto p-4">
        <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">Status flow</p>
        <div className="flex min-w-max items-center gap-1" data-testid="lifecycle-tracker">
          {WA_STATUS_FLOW.map((s, i) => {
            const on = reached.has(s);
            const cur = m.status === s;
            const mm = waMeta(s);
            return (
              <React.Fragment key={s}>
                <div className="flex flex-col items-center gap-1">
                  <div className={`flex h-7 w-7 items-center justify-center rounded-full text-white ${cur ? "ring-2 ring-offset-2" : ""}`}
                    style={{ background: on ? mm.dot : "#e2e8f0", ringColor: mm.dot }} data-testid={`flow-${s}`}>
                    {on ? <Check size={14} weight="bold" /> : <span className="text-[10px] text-slate-400">{i + 1}</span>}
                  </div>
                  <span className={`text-[10px] font-bold ${on ? "text-slate-600" : "text-slate-300"}`}>{mm.label}</span>
                </div>
                {i < WA_STATUS_FLOW.length - 1 && <span className={`h-0.5 w-5 ${on ? "bg-slate-300" : "bg-slate-100"}`} />}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="hivf-card p-4 lg:col-span-2">
          <Row label="Sent To" value={m.sent_to} />
          <Row label="Created On" value={fmt(m.created_at)} />
          <Row label="Created By" value={m.created_by} />
          <Row label="WA Template" value={m.template_name} />
          <Row label="WhatsApp Message ID" value={m.wamid || "— (not returned / queued)"} mono />
          {["failed", "bounced"].includes(m.status) && (
            <>
              <Row label="Failure Type" value={m.failure_type || "—"} />
              <Row label="Failure Reason" value={m.error || "—"} />
              <Row label="Error Code" value={m.error_code != null ? String(m.error_code) : "—"} />
            </>
          )}
          <div className="mt-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Body</p>
            <div className="mt-1 rounded-xl rounded-tl-sm bg-[#dcf8c6] p-3 text-sm text-slate-800 whitespace-pre-wrap" data-testid="message-body">{m.body || "—"}</div>
          </div>
        </div>
        <div className="hivf-card p-4">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Current Status</p>
          <span className={`mt-1 inline-block rounded-full px-3 py-1 text-sm font-bold ${meta.cls}`} data-testid="current-status">{meta.label}</span>
          <p className="mt-4 text-[10px] font-bold uppercase tracking-wider text-slate-400">History</p>
          <div className="mt-1 space-y-1">
            {(m.status_history || []).map((h, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-600">{waMeta(h.status).label}</span>
                <span className="text-slate-400">{fmt(h.at)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const Row = ({ label, value, mono }) => (
  <div className="flex justify-between gap-3 border-b border-slate-50 py-1.5 text-sm">
    <span className="text-slate-400">{label}</span>
    <span className={`text-right font-semibold text-slate-700 ${mono ? "break-all font-mono text-xs" : ""}`}>{value || "—"}</span>
  </div>
);
