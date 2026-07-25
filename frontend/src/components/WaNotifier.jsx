import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WhatsappLogo, X } from "@phosphor-icons/react";
import { toast } from "sonner";
import { API, fmtDate } from "../lib/api";
import { usePoll } from "../hooks/usePoll";

// Global floating "new WhatsApp message" alert — polls unread so no chat is missed.
export default function WaNotifier() {
  const [summary, setSummary] = useState({ total_unread: 0, recent: [] });
  const [open, setOpen] = useState(false);
  const prev = useRef(null);
  const navigate = useNavigate();

  usePoll(async () => {
    const { data } = await API.get("/whatsapp/unread-summary", { noCancel: true });
    if (prev.current !== null && data.total_unread > prev.current) {
      const top = data.recent?.[0];
      toast.message("New WhatsApp message", {
        description: top ? `${top.name} • ${data.total_unread} unread` : `${data.total_unread} unread`,
        action: top ? { label: "Open", onClick: () => navigate(`/whatsapp?channel=${top.id}`) } : undefined,
      });
      setOpen(true);
    }
    prev.current = data.total_unread;
    setSummary(data);
  }, 30000, "wa-unread");

  if (!summary.total_unread) return null;

  return (
    <>
      <button data-testid="wa-notifier-fab" onClick={() => setOpen((v) => !v)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-[#25D366] px-4 py-3 text-white shadow-lg transition-transform hover:scale-105">
        <WhatsappLogo size={22} weight="fill" />
        <span className="text-sm font-extrabold">{summary.total_unread}</span>
      </button>
      {open && (
        <div data-testid="wa-notifier-panel" className="fixed bottom-24 right-6 z-40 w-80 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
          <div className="flex items-center gap-2 bg-[#075E54] px-3 py-2 text-white">
            <WhatsappLogo size={18} weight="fill" />
            <p className="text-sm font-extrabold">Unread WhatsApp</p>
            <button onClick={() => setOpen(false)} className="ml-auto opacity-80 hover:opacity-100"><X size={16} /></button>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {(summary.recent || []).map((c) => (
              <button key={c.id} data-testid={`wa-notifier-item-${c.id}`}
                onClick={() => { navigate(`/whatsapp?channel=${c.id}`); setOpen(false); }}
                className="flex w-full items-center gap-3 border-b border-slate-50 px-3 py-2.5 text-left hover:bg-slate-50">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-600"><WhatsappLogo size={16} weight="duotone" /></div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-extrabold text-slate-800">{c.name}</p>
                  <p className="text-[11px] text-slate-400">{fmtDate(c.last_message_date)}</p>
                </div>
                <span className="rounded-full bg-[#25D366] px-2 py-0.5 text-[10px] font-extrabold text-white">{c.unread_count}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
