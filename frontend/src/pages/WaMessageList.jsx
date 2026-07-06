import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "@phosphor-icons/react";
import { API } from "../lib/api";
import { Spinner, EmptyState } from "../components/Bits";
import { waMeta } from "../lib/waStatus";

const fmt = (s) => {
  if (!s) return "—";
  try { return new Date(s.replace(" ", "T") + "Z").toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch { return s; }
};

export default function WaMessageList() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [tpl, setTpl] = useState(null);

  useEffect(() => {
    API.get(`/templates/whatsapp/${id}`).then(({ data }) => setTpl(data)).catch(() => {});
    API.get(`/wa/template/${id}/messages?limit=200`).then(({ data }) => setData(data));
  }, [id]);

  if (!data) return <Spinner />;
  return (
    <div className="p-6" data-testid="wa-message-list">
      <button onClick={() => navigate(`/templates/whatsapp/${id}`)} className="mb-3 inline-flex items-center gap-1 text-sm font-bold text-slate-400 hover:text-slate-600"><ArrowLeft size={15} /> Back to template</button>
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Message Log{tpl ? ` — ${tpl.name}` : ""}</h1>
      <p className="text-sm text-slate-500">{data.total} message{data.total === 1 ? "" : "s"} triggered from CRM</p>

      {data.items.length === 0 ? <div className="mt-6"><EmptyState title="No messages sent yet" /></div> : (
        <div className="hivf-card mt-4 overflow-hidden">
          <table className="w-full text-sm" data-testid="wa-messages-table">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="px-4 py-2.5">Created On</th>
                <th className="px-4 py-2.5">Created By</th>
                <th className="px-4 py-2.5">Sent To</th>
                <th className="px-4 py-2.5">State</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((m) => {
                const meta = waMeta(m.status);
                return (
                  <tr key={m.id} data-testid={`wa-message-row-${m.id}`} onClick={() => navigate(`/wa/message/${m.id}`)}
                    className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-[#25D366]/5">
                    <td className="px-4 py-2.5 text-slate-600">{fmt(m.created_at)}</td>
                    <td className="px-4 py-2.5 text-slate-600">{m.created_by}</td>
                    <td className="px-4 py-2.5 font-semibold text-[#357ABD]">{m.sent_to || "—"}</td>
                    <td className="px-4 py-2.5"><span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${meta.cls}`}>{meta.label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
