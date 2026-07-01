import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { WhatsappLogo, PaperPlaneTilt, MagnifyingGlass } from "@phosphor-icons/react";
import { toast } from "sonner";
import { API, apiErr, fmtDate } from "../lib/api";
import { Spinner, EmptyState } from "../components/Bits";

export default function WhatsAppInbox() {
  const [params, setParams] = useSearchParams();
  const [channels, setChannels] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [messages, setMessages] = useState(null);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef(null);

  const activeId = params.get("channel") ? parseInt(params.get("channel")) : null;
  const active = channels.find((c) => c.id === activeId);

  const loadChannels = useCallback(async (p = 1, s = "") => {
    const { data } = await API.get("/whatsapp/channels", { params: { page: p, search: s || undefined } });
    setChannels((prev) => (p === 1 ? data.items : [...prev, ...data.items]));
    setTotal(data.total);
    setPage(p);
  }, []);

  useEffect(() => { loadChannels(1, ""); }, [loadChannels]);

  useEffect(() => {
    if (!activeId) return;
    setMessages(null);
    API.get(`/whatsapp/channels/${activeId}/messages`).then(({ data }) => {
      setMessages(data.items);
      setTimeout(() => bottomRef.current?.scrollIntoView(), 50);
    });
  }, [activeId]);

  const send = async () => {
    if (!draft.trim() || !activeId) return;
    try {
      const { data } = await API.post(`/whatsapp/channels/${activeId}/send`, { body: draft.trim() });
      setMessages((m) => [...(m || []), data]);
      setDraft("");
      toast.info("Message queued — will send once WhatsApp API is connected");
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) { toast.error(apiErr(e)); }
  };

  return (
    <div className="flex h-full" data-testid="whatsapp-page">
      {/* Channel list */}
      <div className="flex w-80 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-3">
          <div className="relative">
            <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input data-testid="wa-search-input" value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadChannels(1, search)}
              placeholder="Search conversations…"
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/40" />
          </div>
          <p className="mt-1.5 text-[11px] text-slate-400">{total.toLocaleString("en-IN")} conversations</p>
        </div>
        <div className="flex-1 overflow-y-auto" data-testid="wa-channel-list">
          {channels.map((c) => (
            <button key={c.id} onClick={() => setParams({ channel: String(c.id) })}
              className={`flex w-full items-center gap-3 border-b border-slate-50 px-3 py-2.5 text-left transition-colors ${activeId === c.id ? "bg-emerald-50" : "hover:bg-slate-50"}`}>
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <WhatsappLogo size={18} weight="duotone" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-slate-700">{c.name}</p>
                <p className="text-[11px] text-slate-400">{fmtDate(c.last_message_date)}</p>
              </div>
            </button>
          ))}
          {channels.length < total && (
            <button onClick={() => loadChannels(page + 1, search)} className="w-full py-3 text-xs font-bold text-[#357ABD] hover:bg-slate-50">Load more…</button>
          )}
        </div>
      </div>

      {/* Thread */}
      <div className="flex flex-1 flex-col bg-[#f0f4f8]">
        {!activeId ? (
          <div className="flex flex-1 items-center justify-center">
            <EmptyState title="Select a conversation" subtitle="WhatsApp history migrated from Odoo. Live send/receive activates once Meta API credentials are connected." />
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-600"><WhatsappLogo size={18} weight="duotone" /></div>
              <div>
                <p className="text-sm font-bold text-slate-800" data-testid="wa-thread-title">{active?.name || `Channel ${activeId}`}</p>
                <p className="text-[11px] text-slate-400">{active?.whatsapp_number || ""}</p>
              </div>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto p-4" data-testid="wa-messages">
              {messages === null ? <Spinner /> : messages.map((m) => {
                const outbound = m.direction === "outbound" || (m.author_name && m.author_name !== "Customer" && !/^\+?\d[\d\s]+$/.test(m.author_name) && m.author_name !== active?.name);
                return (
                  <div key={m.id} className={`flex ${outbound ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-md rounded-2xl px-3.5 py-2 text-sm shadow-sm ${outbound ? "rounded-br-md bg-emerald-500 text-white" : "rounded-bl-md bg-white text-slate-700"}`}>
                      {!outbound && <p className="mb-0.5 text-[10px] font-bold text-emerald-600">{m.author_name}</p>}
                      <div className="chatter-body" dangerouslySetInnerHTML={{ __html: m.body }} />
                      <p className={`mt-1 text-right text-[10px] ${outbound ? "text-white/70" : "text-slate-400"}`}>
                        {fmtDate(m.date)}
                        {outbound && m.status && (
                          <span className="ml-1 font-bold" data-testid={`wa-msg-status-${m.id}`}>
                            · {({ queued: "Queued", pending_api_credentials: "Queued", sent: "Sent ✓", delivered: "Delivered ✓✓", read: "Read ✓✓", failed: "Failed ✕", bounced: "Bounced ✕", cancelled: "Cancelled" }[m.status]) || m.status}
                          </span>
                        )}
                        {!outbound && (m.status === "received" || m.direction === "inbound") && <span className="ml-1 font-bold" data-testid={`wa-msg-status-${m.id}`}>· Received</span>}
                      </p>
                    </div>
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>
            <div className="flex items-center gap-2 border-t border-slate-200 bg-white p-3">
              <input data-testid="wa-message-input" value={draft} onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Type a message… (queued until WhatsApp API is connected)"
                className="hivf-input flex-1 !rounded-full" />
              <button data-testid="wa-send-button" onClick={send} className="rounded-full bg-emerald-500 p-2.5 text-white transition-colors hover:bg-emerald-600"><PaperPlaneTilt size={17} /></button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
