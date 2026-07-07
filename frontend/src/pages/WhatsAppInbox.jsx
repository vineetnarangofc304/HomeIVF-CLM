import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  WhatsappLogo, PaperPlaneTilt, MagnifyingGlass, Star, PushPin, Smiley,
  Paperclip, ArrowBendUpLeft, X, Heart, Check, Checks, ChatCircleDots,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { API, apiErr, fmtDate } from "../lib/api";
import { Spinner, EmptyState } from "../components/Bits";
import EmojiPicker from "../components/EmojiPicker";

const token = () => localStorage.getItem("hivf_token") || "";
const mediaSrc = (url) => (url ? `${process.env.REACT_APP_BACKEND_URL}${url}&auth=${encodeURIComponent(token())}` : "");

const FILTERS = [["all", "All"], ["unread", "Unread"], ["interested", "Interested"]];

export default function WhatsAppInbox() {
  const [params, setParams] = useSearchParams();
  const [channels, setChannels] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [messages, setMessages] = useState(null);
  const [draft, setDraft] = useState("");
  const [showEmoji, setShowEmoji] = useState(false);
  const [replyTo, setReplyTo] = useState(null);
  const [msgSearch, setMsgSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [showStarred, setShowStarred] = useState(false);
  const [starred, setStarred] = useState([]);
  const [uploading, setUploading] = useState(false);
  const bottomRef = useRef(null);
  const fileRef = useRef(null);

  const activeId = params.get("channel") ? parseInt(params.get("channel")) : null;
  const active = channels.find((c) => c.id === activeId);

  const loadChannels = useCallback(async (p = 1, s = "", f = "all") => {
    const { data } = await API.get("/whatsapp/channels", { params: { page: p, search: s || undefined, filter: f } });
    setChannels((prev) => (p === 1 ? data.items : [...prev, ...data.items]));
    setTotal(data.total);
    setPage(p);
  }, []);

  useEffect(() => { loadChannels(1, search, filter); /* eslint-disable-next-line */ }, [filter]);

  const loadMessages = useCallback((silent) => {
    if (!activeId) return;
    if (!silent) setMessages(null);
    API.get(`/whatsapp/channels/${activeId}/messages`, { params: { search: msgSearch || undefined } }).then(({ data }) => {
      setMessages((prev) => (silent && prev && prev.length === data.items.length ? prev : data.items));
      if (!silent) setTimeout(() => bottomRef.current?.scrollIntoView(), 50);
    }).catch(() => {});
  }, [activeId, msgSearch]);

  useEffect(() => {
    if (!activeId) return;
    loadMessages(false);
    API.post(`/whatsapp/channels/${activeId}/read`).then(() => {
      setChannels((cs) => cs.map((c) => (c.id === activeId ? { ...c, unread_count: 0 } : c)));
    }).catch(() => {});
  }, [activeId, loadMessages]);

  // Near-real-time polling for open thread + channel list.
  useEffect(() => {
    if (!activeId) return;
    const t = setInterval(() => { loadMessages(true); loadChannels(1, search, filter); }, 8000);
    return () => clearInterval(t);
  }, [activeId, search, filter, loadMessages, loadChannels]);

  const send = async () => {
    if (!draft.trim() || !activeId) return;
    try {
      const { data } = await API.post(`/whatsapp/channels/${activeId}/send`, { body: draft.trim(), reply_to: replyTo?.id || null });
      setMessages((m) => [...(m || []), data]);
      setDraft(""); setReplyTo(null);
      toast[data.status === "sent" ? "success" : "info"](data.status === "sent" ? "Message sent ✓" : "Message queued");
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (e) { toast.error(apiErr(e)); }
  };

  const onFile = async (e) => {
    const file = e.target.files?.[0]; if (!file || !activeId) return;
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data: up } = await API.post("/whatsapp/media/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const { data } = await API.post(`/whatsapp/channels/${activeId}/send`, {
        body: draft.trim(), media_url: up.media_url, media_id: up.media_id, media_type: up.media_type, media_name: up.media_name,
      });
      setMessages((m) => [...(m || []), data]); setDraft("");
      toast[data.status === "sent" ? "success" : "info"](data.status === "sent" ? "Attachment sent ✓" : "Attachment queued");
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (err) { toast.error(apiErr(err)); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  const act = async (m, kind, emoji) => {
    try {
      if (kind === "star") { const { data } = await API.post(`/whatsapp/messages/${m.id}/star`); patchMsg(m.id, { starred: data.starred }); }
      else if (kind === "pin") { const { data } = await API.post(`/whatsapp/messages/${m.id}/pin`); patchMsg(m.id, { pinned: data.pinned }); }
      else if (kind === "react") { const { data } = await API.post(`/whatsapp/messages/${m.id}/react`, { emoji }); patchMsg(m.id, { reaction: data.reaction }); }
    } catch (e) { toast.error(apiErr(e)); }
  };
  const patchMsg = (id, patch) => setMessages((ms) => (ms || []).map((x) => (x.id === id ? { ...x, ...patch } : x)));

  const setCategory = async (cat) => {
    try {
      await API.post(`/whatsapp/channels/${activeId}/category`, { category: cat });
      setChannels((cs) => cs.map((c) => (c.id === activeId ? { ...c, category: cat } : c)));
      toast.success(cat === "interested" ? "Moved to Interested Customer ✓ (lead tagged)" : "Removed from Interested");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const openStarred = async () => {
    setShowStarred(true);
    try { const { data } = await API.get(`/whatsapp/channels/${activeId}/messages`, { params: { starred: true } }); setStarred(data.items); }
    catch (e) { toast.error(apiErr(e)); }
  };

  const pinned = (messages || []).filter((m) => m.pinned);

  const isOut = (m) => m.direction === "outbound";

  return (
    <div className="flex h-full" data-testid="whatsapp-page" style={{ fontFamily: "Nunito, sans-serif" }}>
      {/* Conversation list */}
      <div className="flex w-[340px] shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-3">
          <div className="relative">
            <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input data-testid="wa-search-input" value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadChannels(1, search, filter)}
              placeholder="Search conversations…"
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400/40" />
          </div>
          <div className="mt-2 flex gap-1" data-testid="wa-filter-tabs">
            {FILTERS.map(([k, label]) => (
              <button key={k} data-testid={`wa-filter-${k}`} onClick={() => { setFilter(k); }}
                className={`rounded-full px-3 py-1 text-[12px] font-bold transition-colors ${filter === k ? "bg-[#25D366] text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>{label}</button>
            ))}
            <span className="ml-auto self-center text-[11px] text-slate-400">{total.toLocaleString("en-IN")}</span>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto" data-testid="wa-channel-list">
          {channels.map((c) => {
            const unread = (c.unread_count || 0) > 0;
            return (
            <button key={c.id} data-testid={`wa-channel-${c.id}`} onClick={() => setParams({ channel: String(c.id) })}
              className={`flex w-full items-center gap-3 border-b border-slate-50 px-3 py-2.5 text-left transition-colors ${activeId === c.id ? "bg-emerald-50" : "hover:bg-slate-50"}`}>
              <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <WhatsappLogo size={20} weight="duotone" />
                {c.category === "interested" && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-amber-400 p-0.5"><Star size={9} weight="fill" className="text-white" /></span>}
              </div>
              <div className="min-w-0 flex-1">
                <p className={`truncate text-sm ${unread ? "font-extrabold text-slate-900" : "font-bold text-slate-700"}`}>{c.name}</p>
                <p className={`text-[11px] ${unread ? "font-bold text-emerald-600" : "text-slate-400"}`}>{fmtDate(c.last_message_date)}</p>
              </div>
              {unread && <span data-testid={`wa-unread-${c.id}`} className="ml-1 rounded-full bg-[#25D366] px-2 py-0.5 text-[10px] font-extrabold text-white">{c.unread_count}</span>}
            </button>
          );})}
          {channels.length < total && (
            <button onClick={() => loadChannels(page + 1, search, filter)} className="w-full py-3 text-xs font-bold text-[#357ABD] hover:bg-slate-50">Load more…</button>
          )}
        </div>
      </div>

      {/* Thread */}
      <div className="relative flex flex-1 flex-col bg-[#F0F2F5]">
        {!activeId ? (
          <div className="flex flex-1 items-center justify-center">
            <EmptyState title="Select a conversation" subtitle="Live 2-way WhatsApp. Unread chats are bold with a green badge." />
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-600"><WhatsappLogo size={18} weight="duotone" /></div>
              <div className="mr-auto">
                <p className="text-sm font-extrabold text-slate-800" data-testid="wa-thread-title">{active?.name || `Channel ${activeId}`}</p>
                <p className="text-[11px] text-slate-400">{active?.whatsapp_number || active?.phone_digits || ""}</p>
              </div>
              <button data-testid="wa-interested-toggle" onClick={() => setCategory(active?.category === "interested" ? null : "interested")}
                className={`inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-bold ${active?.category === "interested" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
                <Star size={13} weight={active?.category === "interested" ? "fill" : "regular"} /> Interested
              </button>
              <button data-testid="wa-search-toggle" onClick={() => { setShowSearch((v) => !v); }} className="rounded-full p-2 text-slate-400 hover:bg-slate-100"><MagnifyingGlass size={17} /></button>
              <button data-testid="wa-starred-toggle" onClick={openStarred} className="rounded-full p-2 text-slate-400 hover:bg-slate-100"><Star size={17} /></button>
            </div>

            {showSearch && (
              <div className="border-b border-slate-200 bg-white px-4 py-2">
                <input data-testid="wa-msg-search" autoFocus value={msgSearch} onChange={(e) => setMsgSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && loadMessages(false)}
                  placeholder="Search in this conversation… (Enter)" className="hivf-input !rounded-full text-sm" />
              </div>
            )}

            {pinned.length > 0 && (
              <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-[11px] text-amber-800" data-testid="wa-pinned-bar">
                <PushPin size={13} weight="fill" /> <span className="truncate">{pinned[pinned.length - 1].body}</span>
                <span className="ml-auto font-bold">{pinned.length} pinned</span>
              </div>
            )}

            <div className="flex-1 space-y-1.5 overflow-y-auto p-4" data-testid="wa-messages">
              {messages === null ? <Spinner /> : messages.length === 0 ? <p className="mt-10 text-center text-sm text-slate-400">No messages{msgSearch ? " match your search" : " yet"}.</p> : messages.map((m) => {
                const out = isOut(m);
                return (
                  <div key={m.id} data-testid={`wa-msg-${m.id}`} className={`group flex ${out ? "justify-end" : "justify-start"}`}>
                    <div className={`relative max-w-md rounded-2xl px-3 py-2 text-sm shadow-sm ${out ? "rounded-br-md bg-[#DCF8C6] text-slate-800" : "rounded-bl-md bg-white text-slate-700"}`}>
                      {!out && <p className="mb-0.5 text-[10px] font-bold text-emerald-600">{m.author_name}</p>}
                      {m.reply_to && <div className="mb-1 rounded-lg border-l-2 border-emerald-400 bg-black/5 px-2 py-1 text-[11px] text-slate-500"><b>{m.reply_to.author}</b><br />{m.reply_to.body}</div>}
                      {m.media_url && (m.media_type === "image"
                        ? <img src={mediaSrc(m.media_url)} alt="attachment" className="mb-1 max-h-52 rounded-lg" />
                        : <a href={mediaSrc(m.media_url)} target="_blank" rel="noreferrer" className="mb-1 flex items-center gap-1 text-[12px] font-bold text-[#357ABD] underline"><Paperclip size={13} /> {m.media_name || m.media_type || "attachment"}</a>)}
                      {m.body && <div className="chatter-body whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: m.body }} />}
                      <p className={`mt-0.5 flex items-center justify-end gap-1 text-[10px] ${out ? "text-slate-500" : "text-slate-400"}`}>
                        {m.starred && <Star size={11} weight="fill" className="text-amber-500" />}
                        {m.pinned && <PushPin size={11} weight="fill" className="text-amber-500" />}
                        {fmtDate(m.date)}
                        {out && <span data-testid={`wa-msg-status-${m.id}`} className="font-bold">{({ queued: "Queued", pending_api_credentials: "Queued", sent: "✓", delivered: "✓✓", read: "✓✓", failed: "✕", replied: "✓✓" }[m.status]) || "✓"}</span>}
                      </p>
                      {m.reaction && <span data-testid={`wa-reaction-${m.id}`} className="absolute -bottom-2 right-2 rounded-full border border-slate-200 bg-white px-1 text-xs shadow-sm">{m.reaction}</span>}
                      {/* hover actions */}
                      <div className={`absolute top-1 ${out ? "-left-24" : "-right-24"} hidden gap-0.5 rounded-full border border-slate-200 bg-white px-1 py-0.5 shadow group-hover:flex`}>
                        <button data-testid={`wa-react-${m.id}`} onClick={() => act(m, "react", "👍")} className="rounded-full p-1 hover:bg-slate-100" title="React 👍"><Heart size={13} className="text-rose-400" /></button>
                        <button data-testid={`wa-reply-${m.id}`} onClick={() => setReplyTo({ id: m.id, author: m.author_name, body: m.body })} className="rounded-full p-1 hover:bg-slate-100" title="Reply"><ArrowBendUpLeft size={13} className="text-slate-500" /></button>
                        <button data-testid={`wa-star-${m.id}`} onClick={() => act(m, "star")} className="rounded-full p-1 hover:bg-slate-100" title="Star"><Star size={13} className={m.starred ? "text-amber-500" : "text-slate-500"} weight={m.starred ? "fill" : "regular"} /></button>
                        <button data-testid={`wa-pin-${m.id}`} onClick={() => act(m, "pin")} className="rounded-full p-1 hover:bg-slate-100" title="Pin"><PushPin size={13} className={m.pinned ? "text-amber-500" : "text-slate-500"} weight={m.pinned ? "fill" : "regular"} /></button>
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>

            {replyTo && (
              <div className="flex items-center gap-2 border-t border-slate-200 bg-white px-4 py-1.5 text-[12px]" data-testid="wa-reply-preview">
                <ArrowBendUpLeft size={14} className="text-emerald-500" />
                <span className="truncate text-slate-500">Replying to <b>{replyTo.author}</b>: {replyTo.body}</span>
                <button onClick={() => setReplyTo(null)} className="ml-auto text-slate-400 hover:text-slate-600"><X size={14} /></button>
              </div>
            )}

            <div className="relative flex items-center gap-2 border-t border-slate-200 bg-white p-3">
              {showEmoji && <EmojiPicker onPick={(e) => setDraft((d) => d + e)} onClose={() => setShowEmoji(false)} />}
              <button data-testid="wa-emoji-btn" onClick={() => setShowEmoji((v) => !v)} className="rounded-full p-2 text-slate-400 hover:bg-slate-100"><Smiley size={20} /></button>
              <input ref={fileRef} type="file" className="hidden" onChange={onFile} data-testid="wa-file-input" accept="image/*,video/*,application/pdf,.doc,.docx,.xls,.xlsx" />
              <button data-testid="wa-attach-btn" disabled={uploading} onClick={() => fileRef.current?.click()} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 disabled:opacity-50"><Paperclip size={19} /></button>
              <input data-testid="wa-message-input" value={draft} onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder={uploading ? "Uploading…" : "Type a message…"}
                className="hivf-input flex-1 !rounded-full" />
              <button data-testid="wa-send-button" onClick={send} className="rounded-full bg-[#25D366] p-2.5 text-white transition-colors hover:bg-emerald-600"><PaperPlaneTilt size={17} weight="fill" /></button>
            </div>
          </>
        )}

        {/* Starred panel */}
        {showStarred && (
          <div className="absolute right-0 top-0 z-20 flex h-full w-80 flex-col border-l border-slate-200 bg-white shadow-xl" data-testid="wa-starred-panel">
            <div className="flex items-center gap-2 border-b border-slate-100 p-3">
              <Star size={16} weight="fill" className="text-amber-500" />
              <p className="text-sm font-extrabold text-slate-800">Starred messages</p>
              <button onClick={() => setShowStarred(false)} className="ml-auto text-slate-400 hover:text-slate-600"><X size={16} /></button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto p-3">
              {starred.length === 0 ? <p className="mt-6 text-center text-xs text-slate-400">No starred messages yet.</p> :
                starred.map((m) => (
                  <div key={m.id} className="rounded-xl border border-slate-100 bg-slate-50 p-2 text-[12px] text-slate-600">
                    <p className="mb-0.5 text-[10px] font-bold text-slate-400">{m.author_name} · {fmtDate(m.date)}</p>
                    <div className="whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: m.body || m.media_name || "[media]" }} />
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
