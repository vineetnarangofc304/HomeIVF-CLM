import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, NotePencil, PaperPlaneTilt, CalendarCheck, Sparkle, Prohibit,
  ArrowCounterClockwise, WhatsappLogo, CheckCircle, XCircle, EnvelopeSimple, Plus,
  Phone, PhoneIncoming, PhoneOutgoing, Paperclip, UploadSimple, DownloadSimple, Trash, Warning, Eye, X, ArrowRight,
} from "@phosphor-icons/react";
import { API, apiErr, fmtDate, fmtDay, todayStr } from "../lib/api";
import { useAuth, useCatalogMaps, useCatalogs } from "../context/AuthContext";
import { useNavGuard } from "../context/NavGuardContext";
import { TagChip, Spinner, EmptyState } from "../components/Bits";
import { waMeta } from "../lib/waStatus";

export default function LeadDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { catalogs, tagById, userById, lostById } = useCatalogMaps();
  const { refreshCatalogs } = useCatalogs();
  const { registerGuard, clearGuard, isBlocked, checkAllowed } = useNavGuard();
  const [lead, setLead] = useState(null);
  const [messages, setMessages] = useState([]);
  const [msgTotal, setMsgTotal] = useState(0);
  const [msgPage, setMsgPage] = useState(1);
  const [activities, setActivities] = useState([]);
  const [waChannels, setWaChannels] = useState([]);
  const [calls, setCalls] = useState([]);
  const [attachments, setAttachments] = useState([]);
  const [dialing, setDialing] = useState(false);
  const [tab, setTab] = useState("chatter");
  const [note, setNote] = useState("");
  const [showActivity, setShowActivity] = useState(false);
  const [showLost, setShowLost] = useState(false);
  const [showWa, setShowWa] = useState(false);
  const [showEmail, setShowEmail] = useState(false);
  const [showNewTag, setShowNewTag] = useState(false);
  const [viewAtt, setViewAtt] = useState(null);
  const [waTrackById, setWaTrackById] = useState({});
  const [fuCount, setFuCount] = useState(null);

  const load = useCallback(async () => {
    try {
      const [{ data: l }, { data: m }, { data: a }, { data: w }, { data: c }, { data: at }] = await Promise.all([
        API.get(`/leads/${id}`),
        API.get(`/leads/${id}/messages`, { params: { page: 1 } }),
        API.get(`/leads/${id}/activities`),
        API.get(`/whatsapp/lead/${id}`),
        API.get(`/calls/lead/${id}`),
        API.get(`/leads/${id}/attachments`),
      ]);
      setLead(l);
      setMessages(m.items);
      setMsgTotal(m.total);
      setMsgPage(1);
      setActivities(a);
      setWaChannels(w);
      setCalls(c);
      setAttachments(at);
      API.get(`/wa/lead/${id}/messages`).then(({ data }) => {
        const map = {}; (data || []).forEach((t) => { map[t.id] = t; });
        setWaTrackById(map);
      }).catch(() => {});
    } catch (e) {
      toast.error(apiErr(e));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // --- Mandatory-field navigation guard: City, State, Disposition Tag, Caller Activity ---
  const touchedRef = useRef(false);
  const leadRef = useRef(lead);
  const callerActCountRef = useRef(0);
  useEffect(() => { leadRef.current = lead; });
  useEffect(() => { touchedRef.current = false; callerActCountRef.current = 0; }, [id]); // reset when a different lead opens

  useEffect(() => {
    // Block leaving ONLY after the user edits something on an ACTIVE lead while a
    // mandatory field is still empty. Returns the list of missing field labels.
    registerGuard(() => {
      const l = leadRef.current;
      if (!l || !l.active || !touchedRef.current) return null;
      const miss = [];
      if (!(l.city && String(l.city).trim())) miss.push("City");
      if (!(l.state_name && String(l.state_name).trim())) miss.push("State");
      if (!((l.tags || []).length)) miss.push("Disposition Tag");
      if (!callerActCountRef.current) miss.push("Caller Activity");
      return miss.length ? miss : null;
    });
    return () => clearGuard();
  }, [registerGuard, clearGuard]);

  // Warn on tab close / refresh and trap the browser Back button while blocked.
  useEffect(() => {
    const onBeforeUnload = (e) => { if (isBlocked()) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", onBeforeUnload);
    window.history.pushState(null, "", window.location.href); // sentinel entry
    const onPop = () => {
      if (isBlocked()) {
        window.history.pushState(null, "", window.location.href); // re-trap
        checkAllowed(); // show the mandatory-fields popup
      } else {
        window.removeEventListener("popstate", onPop);
        window.history.back(); // fields OK — allow the real Back
      }
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("popstate", onPop);
    };
  }, [isBlocked, checkAllowed]);

  const reloadMessages = async () => {
    const { data: m } = await API.get(`/leads/${id}/messages`, { params: { page: 1 } });
    setMessages(m.items); setMsgTotal(m.total); setMsgPage(1);
  };

  const update = async (updates) => {
    touchedRef.current = true;
    try {
      const { data } = await API.patch(`/leads/${id}`, { updates });
      setLead(data);
      await reloadMessages();
      toast.success("Updated");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const postNote = async () => {
    if (!note.trim()) return;
    try {
      const { data } = await API.post(`/leads/${id}/messages`, { body: note.trim().replace(/\n/g, "<br/>"), subtype: "note" });
      setMessages((m) => [data, ...m]);
      setNote("");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const loadMoreMsgs = async () => {
    const next = msgPage + 1;
    const { data: m } = await API.get(`/leads/${id}/messages`, { params: { page: next } });
    setMessages((prev) => [...prev, ...m.items]);
    setMsgPage(next);
  };

  const clickToDial = async () => {
    setDialing(true);
    try {
      await API.post(`/calls/dial`, { lead_id: lead.id });
      toast.success("Call queued via Ozonetel — the dialer will connect you shortly");
      const { data: c } = await API.get(`/calls/lead/${id}`);
      setCalls(c);
      await reloadMessages();
    } catch (e) { toast.error(apiErr(e)); }
    finally { setDialing(false); }
  };

  const [moving, setMoving] = useState(false);
  const moveToPipeline = async () => {
    setMoving(true);
    try {
      const { data } = await API.post(`/leads/${id}/promote-to-pipeline`, {
        contact_name: lead.contact_name || lead.name, phone: lead.phone,
        email_from: lead.email_from, city: lead.city, state_name: lead.state_name,
      });
      toast.success(data.merged_into ? `Merged into existing pipeline lead #${data.merged_into}` : "Moved to Lead in Pipeline ✓");
      if (data.merged_into) navigate(`/leads/${data.merged_into}`);
      else load();
    } catch (e) { toast.error(apiErr(e)); }
    finally { setMoving(false); }
  };

  const reloadAttachments = async () => {
    const { data } = await API.get(`/leads/${id}/attachments`);
    setAttachments(data);
  };

  const uploadFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    for (const f of files) {
      if (f.size > 25 * 1024 * 1024) { toast.error(`${f.name} exceeds 25MB`); continue; }
      const fd = new FormData();
      fd.append("file", f);
      try {
        await API.post(`/leads/${id}/attachments`, fd, { headers: { "Content-Type": "multipart/form-data" } });
        toast.success(`Uploaded ${f.name}`);
      } catch (e) { toast.error(apiErr(e)); }
    }
    await reloadAttachments();
    await reloadMessages();
  };

  const deleteAttachment = async (att) => {
    if (!window.confirm(`Delete ${att.original_filename}?`)) return;
    await API.delete(`/attachments/${att.id}`);
    await reloadAttachments();
  };

  const downloadAttachment = async (att) => {
    try {
      const res = await API.get(`/attachments/${att.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = att.original_filename || "file";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { toast.error(apiErr(e)); }
  };

  const previewAttachment = async (att) => {
    try {
      const res = await API.get(`/attachments/${att.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      setViewAtt({ url, type: att.content_type || res.data.type || "", name: att.original_filename || "file" });
    } catch (e) { toast.error(apiErr(e)); }
  };

  if (!lead) return <Spinner />;

  const leadStages = (catalogs?.lead_stage || []).map((s) => s.name);
  const fieldLabels = catalogs?.field_labels || {};
  const labelOf = (k) => fieldLabels[k]?.label || k.replace("x_studio_", "").replace(/_/g, " ");
  // Case 3 — Disposition Tag → Lead Stage dependent mapping (reverse lookup: tag → stage).
  const dispMap = catalogs?.disposition_map || {};
  const dispReverse = {};
  Object.entries(dispMap).forEach(([stage, tags]) => (tags || []).forEach((t) => { dispReverse[t] = stage; }));

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="lead-detail-page">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <button data-testid="back-button" onClick={() => { if (checkAllowed()) navigate(-1); }} className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100"><ArrowLeft size={18} /></button>
          <div className="mr-auto">
            <h1 className="font-display text-lg font-extrabold text-slate-900" data-testid="lead-name">{lead.contact_name || lead.name}</h1>
            <p className="text-xs text-slate-500">#{lead.id} · created {fmtDate(lead.create_date)} {!lead.active && <span className="ml-1 font-bold uppercase text-rose-500">Lost{lead.lost_reason_id ? ` — ${lostById[lead.lost_reason_id]?.name || ""}` : ""}</span>}</p>
          </div>
          {lead.is_duplicate && (
            <button data-testid="duplicate-badge" onClick={() => lead.duplicate_of && checkAllowed() && navigate(`/leads/${lead.duplicate_of}`)}
              title={`Same phone as lead #${lead.duplicate_of}`}
              className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold text-amber-700 hover:bg-amber-200">
              <Warning size={14} weight="fill" /> Duplicate{lead.duplicate_of ? ` of #${lead.duplicate_of}` : ""}
            </button>
          )}
          {lead.ozonetel_lead && !lead.in_pipeline && (
            <button data-testid="move-to-pipeline-button" onClick={moveToPipeline} disabled={moving}
              className="inline-flex items-center gap-1.5 rounded-full bg-[#4A90E2] px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-[#357ABD] disabled:opacity-60">
              <ArrowRight size={15} weight="bold" /> {moving ? "Moving…" : "Move to Pipeline"}
            </button>
          )}
          <button data-testid="click-to-dial-button" onClick={clickToDial} disabled={dialing}
            className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500 px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-indigo-600 disabled:opacity-60">
            <Phone size={15} weight="bold" /> {dialing ? "Dialing…" : "Call"}
          </button>
          <button data-testid="send-whatsapp-button" onClick={() => setShowWa(true)}
            className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-emerald-600">
            <WhatsappLogo size={15} weight="bold" /> WhatsApp
          </button>
          <button data-testid="send-email-button" onClick={() => setShowEmail(true)}
            className="inline-flex items-center gap-1.5 rounded-full bg-[#4A90E2] px-3 py-1.5 text-xs font-bold text-white transition-colors hover:bg-[#357ABD]">
            <EnvelopeSimple size={15} weight="bold" /> Email
          </button>
          <div className="flex overflow-hidden rounded-full border border-slate-200" data-testid="lead-stage-stepper">
            {leadStages.map((s) => (
              <button key={s} data-testid={`stage-btn-${s.replace(/\s/g, "-")}`} onClick={() => update({ lead_stage: s })}
                className={`px-3 py-1.5 text-xs font-bold transition-colors ${lead.lead_stage === s ? "bg-[#4A90E2] text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}>
                {s}
              </button>
            ))}
          </div>
          {lead.active ? (
            <button data-testid="mark-lost-button" onClick={() => setShowLost(true)} className="hivf-btn-secondary !py-1.5 text-xs text-rose-600"><Prohibit size={14} /> Lost</button>
          ) : (
            <button data-testid="restore-button" onClick={async () => { await API.post(`/leads/${id}/restore`); load(); }} className="hivf-btn-secondary !py-1.5 text-xs text-emerald-600"><ArrowCounterClockwise size={14} /> Restore</button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto lg:overflow-hidden">
      <div className="grid grid-cols-1 gap-5 p-5 lg:grid-cols-5 lg:h-full">
        {/* LEFT: fields */}
        <div className="space-y-4 lg:col-span-2 lg:h-full lg:overflow-y-auto lg:min-h-0 lg:pr-1">
          <div className="rounded-2xl border border-[#8B5CF6]/20 bg-gradient-to-br from-[#8B5CF6]/5 to-[#4A90E2]/5 p-4">
            <div className="flex items-center gap-2 text-[#8B5CF6]"><Sparkle size={15} weight="fill" /><span className="text-xs font-bold">AI Summary</span></div>
            <p className="mt-1 text-xs text-slate-500">AI insights & next-best-action arrive in Phase 2.</p>
          </div>

          <FieldCard title="Contact" lead={lead} onSave={update}
            fields={[
              ["contact_name", "Name"], ["phone", "Phone"], ["alternate_number", "Alternate Number"],
              ["email_from", "Email"], ["street", "Address"], ["city", "City"],
              ["state_name", "State", "select"], ["country", "Country", "select"],
            ]}
            required={["city", "state_name"]}
            defaults={{ country: "India" }}
            selects={{
              state_name: (catalogs?.state || []).map((s) => s.name),
              country: (catalogs?.country || []).map((c) => c.name),
            }} />

          {/* Meta / Google Q&A — Case 3 */}
          <QACard lead={lead} onSave={update} catalogs={catalogs} labelOf={labelOf} />

          <FieldCard title="Case Details" lead={lead} onSave={update} fields={[
            ["gender", "Gender"], ["male_age", "Male Age"], ["female_age", "Female Age"],
            ["spouse_name", "Spouse Name"], ["pre_conditions", "Pre-conditions"],
            ["doctor_name", "Doctor"], ["query", "Query"], ["remark", "Remark"],
          ]} />

          {/* Admin-defined custom fields (Case 4) — general section */}
          <CustomFieldsCard lead={lead} onSave={update} catalogs={catalogs} />

          {/* Assignment & follow-up */}
          <div className="hivf-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-display text-sm font-extrabold text-slate-800">Assignment &amp; Follow-up</h3>
              {fuCount != null && (
                <span data-testid="total-followup-count" className="rounded-full bg-[#4A90E2]/10 px-2.5 py-0.5 text-[11px] font-bold text-[#357ABD]">
                  Total Follow-up: {fuCount}
                </span>
              )}
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Caller</label>
              <select data-testid="assignee-select" disabled={user.role === "caller"} className="hivf-select mt-1 w-full" value={lead.user_id || ""} onChange={(e) => update({ user_id: e.target.value ? parseInt(e.target.value) : null })}>
                <option value="">Unassigned</option>
                {(catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </div>
            <FollowUpSection leadId={lead.id} catalogs={catalogs} onChanged={load} onCount={setFuCount} />
          </div>

          {/* Caller Activities — Case 2 */}
          <CallerActivities leadId={lead.id} onCount={(n) => { callerActCountRef.current = n; }} />

          <WaLeadPanel leadId={lead.id} />

          {/* Tags — Case 2: inline new-tag creation. Case 3: tag→stage dependent mapping */}
          <div className="hivf-card p-4">
            <div className="flex items-center justify-between">
              <h3 className="mb-2 font-display text-sm font-extrabold text-slate-800">
                Disposition Tags
                {(lead.tags || []).length === 0 && <span className="ml-1.5 text-[10px] font-bold text-rose-500" data-testid="disposition-required">* Required</span>}
              </h3>
              <button data-testid="new-tag-button" onClick={() => setShowNewTag(true)}
                className="inline-flex items-center gap-1 rounded-full border border-dashed border-[#4A90E2]/50 px-2.5 py-1 text-[11px] font-bold text-[#357ABD] transition-colors hover:bg-[#4A90E2]/10">
                <Plus size={12} /> New tag
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5" data-testid="lead-tags">
              {(lead.tags || []).map((t) => (
                <TagChip key={t} tag={tagById[t]} onRemove={() => update({ tags: lead.tags.filter((x) => x !== t) })} />
              ))}
            </div>
            <select data-testid="add-tag-select" className="hivf-select mt-3 w-full" value=""
              onChange={(e) => {
                const v = parseInt(e.target.value);
                if (!v || (lead.tags || []).includes(v)) return;
                const tagName = tagById[v]?.name;
                const stage = dispReverse[tagName];
                const upd = { tags: [...(lead.tags || []), v] };
                if (stage && stage !== lead.lead_stage) upd.lead_stage = stage;
                update(upd);
                if (stage && stage !== lead.lead_stage) toast.success(`Stage set to "${stage}" for "${tagName}"`);
              }}>
              <option value="">+ Add disposition tag…</option>
              {Object.entries(dispMap).map(([stage, tags]) => {
                const opts = (catalogs?.tag || []).filter((t) => t.active !== false && !(lead.tags || []).includes(t.id) && (tags || []).includes(t.name));
                return opts.length ? <optgroup key={stage} label={stage}>{opts.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup> : null;
              })}
              {(() => {
                const mapped = new Set(Object.values(dispMap).flat());
                const other = (catalogs?.tag || []).filter((t) => t.active !== false && !(lead.tags || []).includes(t.id) && !mapped.has(t.name));
                return other.length ? <optgroup label="Other">{other.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup> : null;
              })()}
            </select>
          </div>

          {/* Attribution + UTM — Case 7 */}
          <FieldCard title="Attribution" lead={lead} onSave={update}
            fields={[
              ["source_lead", "Source"], ["ads_platform", "Ads Platform"], ["campaign_name", "Campaign"],
              ["ads_campaign_name", "Ads Campaign"], ["ads_name", "Ad Name"],
              ["conversion_page", "Conversion Page"],
              ["source_id", "UTM Source", "select"], ["medium_id", "UTM Medium", "select"],
              ["campaign_id", "UTM Campaign", "select"],
            ]}
            selects={{
              source_id: (catalogs?.utm_source || []).map((s) => s.name),
              medium_id: (catalogs?.utm_medium || []).map((s) => s.name),
              campaign_id: (catalogs?.utm_campaign || []).map((s) => s.name),
            }} />

          {/* Additional imported fields with proper labels */}
          {lead.custom && Object.keys(lead.custom).length > 0 && (
            <details className="hivf-card p-4">
              <summary className="cursor-pointer font-display text-sm font-extrabold text-slate-800">Additional fields ({Object.keys(lead.custom).length})</summary>
              <div className="mt-3 max-h-72 space-y-1 overflow-y-auto text-xs">
                {Object.entries(lead.custom).map(([k, v]) => (
                  <div key={k} className="flex gap-2 border-b border-slate-50 py-1">
                    <span className="w-1/2 shrink-0 truncate font-semibold text-slate-500" title={k}>{labelOf(k)}</span>
                    <span className="text-slate-700">{Array.isArray(v) ? v[1] ?? v.join(",") : String(v)}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* RIGHT: chatter */}
        <div className="lg:col-span-3 lg:h-full lg:overflow-y-auto lg:min-h-0">
          <div className="hivf-card">
            <div className="flex items-center gap-1 border-b border-slate-100 px-4 pt-3">
              {[["chatter", "Chatter", msgTotal], ["activities", "Activities", activities.length], ["whatsapp", "WhatsApp", waChannels.length], ["calls", "Calls", calls.length], ["attachments", "Attachments", attachments.length]].map(([k, l, c]) => (
                <button key={k} data-testid={`tab-${k}`} onClick={() => setTab(k)}
                  className={`rounded-t-lg px-3 py-2 text-sm font-bold transition-colors ${tab === k ? "border-b-2 border-[#4A90E2] text-[#357ABD]" : "text-slate-500 hover:text-slate-700"}`}>
                  {l} {c > 0 && <span className="ml-1 rounded-full bg-slate-100 px-1.5 text-[10px]">{c}</span>}
                </button>
              ))}
              <div className="flex-1" />
              <button data-testid="schedule-activity-button" onClick={() => setShowActivity(true)} className="mb-1 hivf-btn-secondary !px-2.5 !py-1 text-xs"><CalendarCheck size={13} /> Schedule</button>
            </div>

            {tab === "chatter" && (
              <div className="p-4">
                <div className="flex gap-2">
                  <textarea data-testid="note-input" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                    placeholder="Log a note… (call outcome, remarks)" className="hivf-input flex-1" />
                  <button data-testid="post-note-button" onClick={postNote} className="hivf-btn-primary self-end !px-3"><PaperPlaneTilt size={15} /></button>
                </div>
                <div className="mt-4 space-y-3" data-testid="chatter-list">
                  {messages.map((m) => (
                    <div key={m.id} className={`rounded-xl border p-3 ${m.subtype === "note" ? "border-amber-100 bg-amber-50/50" : m.subtype === "comment" ? "border-blue-100 bg-blue-50/40" : "border-slate-100 bg-white"}`} data-testid={`chatter-msg-${m.id}`}>
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-700">{m.author_name || "System"}</span>
                        <span className="text-[11px] text-slate-400">{fmtDate(m.date)}</span>
                      </div>
                      {m.subject && !m.kind && <p className="text-xs font-semibold text-slate-600">{m.subject}</p>}
                      <div className="chatter-body text-sm text-slate-700" dangerouslySetInnerHTML={{ __html: m.body }} />
                      {(m.kind === "wa_template" || m.kind === "email_template") && (
                        <TemplateActivityPreview m={m} liveStatus={m.track_id ? waTrackById[m.track_id]?.status : null} navigate={navigate} />
                      )}
                    </div>
                  ))}
                  {messages.length < msgTotal && (
                    <button onClick={loadMoreMsgs} className="hivf-btn-secondary w-full justify-center text-xs" data-testid="load-more-messages">
                      Load older ({msgTotal - messages.length} more)
                    </button>
                  )}
                  {messages.length === 0 && <EmptyState title="No history yet" subtitle="Log your first note above" />}
                </div>
              </div>
            )}

            {tab === "activities" && (
              <div className="space-y-2 p-4" data-testid="activities-list">
                {activities.length === 0 && <EmptyState title="No scheduled activities" />}
                {activities.map((a) => (
                  <div key={a.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3">
                    <CalendarCheck size={18} className={a.date_deadline < todayStr() ? "text-rose-500" : "text-[#4A90E2]"} />
                    <div className="flex-1">
                      <p className="text-sm font-bold text-slate-700">{a.type_name}{a.summary ? ` — ${a.summary}` : ""}</p>
                      <p className="text-xs text-slate-500">Due {fmtDay(a.date_deadline)} · {userById[a.user_id]?.name || ""}</p>
                    </div>
                    <button data-testid={`activity-done-${a.id}`} title="Mark done" onClick={async () => { await API.post(`/activities/${a.id}/done`, {}); load(); }} className="text-emerald-500 hover:text-emerald-600"><CheckCircle size={20} /></button>
                    <button title="Cancel" onClick={async () => { await API.post(`/activities/${a.id}/cancel`); load(); }} className="text-slate-300 hover:text-rose-500"><XCircle size={20} /></button>
                  </div>
                ))}
              </div>
            )}

            {tab === "whatsapp" && (
              <div className="p-4" data-testid="lead-whatsapp">
                {waChannels.length === 0 ? (
                  <EmptyState title="No WhatsApp conversation found" subtitle="Matched by phone number" />
                ) : (
                  waChannels.map((c) => (
                    <Link key={c.id} to={`/whatsapp?channel=${c.id}`} className="flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50/40 p-3 transition-colors hover:bg-emerald-50">
                      <WhatsappLogo size={22} weight="duotone" className="text-emerald-600" />
                      <div>
                        <p className="text-sm font-bold text-slate-700">{c.name}</p>
                        <p className="text-xs text-slate-500">Last activity {fmtDate(c.last_message_date)}</p>
                      </div>
                    </Link>
                  ))
                )}
              </div>
            )}
            {tab === "calls" && (
              <div className="space-y-2 p-4" data-testid="lead-calls-list">
                {calls.length === 0 && <EmptyState title="No calls yet" subtitle="Incoming Ozonetel calls & click-to-dial attempts appear here" />}
                {calls.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3" data-testid={`call-row-${c.id}`}>
                    {c.direction === "incoming"
                      ? <PhoneIncoming size={18} weight="duotone" className="text-emerald-500" />
                      : <PhoneOutgoing size={18} weight="duotone" className="text-indigo-500" />}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-bold text-slate-700">
                        {c.direction === "incoming" ? "Incoming call" : "Outbound (click-to-dial)"} · {c.phone || "—"}
                      </p>
                      <p className="text-xs text-slate-500">
                        {fmtDate(c.created_at)}{c.agent_name ? ` · ${c.agent_name}` : ""}
                        {c.status ? ` · ${c.status}` : ""}{c.duration ? ` · ${c.duration}s` : ""}
                        {c.disposition ? ` · ${c.disposition}` : ""}
                      </p>
                      {c.recording_url && (
                        <audio controls preload="none" src={c.recording_url} className="mt-2 h-8 w-full max-w-xs" data-testid={`call-recording-${c.id}`} />
                      )}
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${c.status === "failed" ? "bg-rose-50 text-rose-600" : c.status === "connected" ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-500"}`}>
                      {c.status || c.call_type || c.direction}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {tab === "attachments" && (
              <div className="p-4" data-testid="lead-attachments-panel">
                <label className="mb-3 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 py-8 text-center transition-colors hover:border-[#4A90E2] hover:bg-[#4A90E2]/5"
                  data-testid="attachment-dropzone">
                  <UploadSimple size={24} className="text-[#4A90E2]" />
                  <span className="text-sm font-bold text-slate-600">Click to upload medical reports / documents</span>
                  <span className="text-xs text-slate-400">PDF, images, docs — up to 25MB each</span>
                  <input type="file" multiple className="hidden" data-testid="attachment-file-input"
                    onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
                </label>
                {attachments.length === 0 ? (
                  <EmptyState title="No attachments yet" subtitle="Upload patient reports, scans and documents here" />
                ) : (
                  <div className="space-y-2" data-testid="attachments-list">
                    {attachments.map((a) => (
                      <div key={a.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3" data-testid={`attachment-row-${a.id}`}>
                        <Paperclip size={18} className="text-slate-400" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-bold text-slate-700">{a.original_filename}</p>
                          <p className="text-xs text-slate-500">{(a.size / 1024).toFixed(0)} KB · {a.uploaded_by} · {fmtDate(a.created_at)}</p>
                        </div>
                        <button onClick={() => previewAttachment(a)} className="text-slate-400 hover:text-[#8B5CF6]" data-testid={`attachment-view-${a.id}`} title="View"><Eye size={18} /></button>
                        <button onClick={() => downloadAttachment(a)} className="text-slate-400 hover:text-[#4A90E2]" data-testid={`attachment-download-${a.id}`} title="Download"><DownloadSimple size={18} /></button>
                        <button onClick={() => deleteAttachment(a)} className="text-slate-400 hover:text-rose-500" data-testid={`attachment-delete-${a.id}`} title="Delete"><Trash size={18} /></button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      </div>

      {showActivity && <ActivityModal leadId={lead.id} onClose={() => setShowActivity(false)} onSaved={() => { setShowActivity(false); load(); }} catalogs={catalogs} />}
      {showLost && <LostModal leadId={lead.id} onClose={() => setShowLost(false)} onSaved={() => { setShowLost(false); load(); }} catalogs={catalogs} />}
      {showWa && <SendWhatsAppModal lead={lead} onClose={() => setShowWa(false)} onSent={() => { setShowWa(false); reloadMessages(); }} />}
      {viewAtt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4" onClick={() => { URL.revokeObjectURL(viewAtt.url); setViewAtt(null); }} data-testid="attachment-viewer">
          <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl bg-white p-3 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <p className="truncate text-sm font-bold text-slate-700">{viewAtt.name}</p>
              <button onClick={() => { URL.revokeObjectURL(viewAtt.url); setViewAtt(null); }} className="text-slate-400 hover:text-rose-500" data-testid="attachment-viewer-close"><X size={20} /></button>
            </div>
            <div className="flex-1 overflow-auto rounded-xl bg-slate-50">
              {viewAtt.type.startsWith("image/") ? (
                <img src={viewAtt.url} alt={viewAtt.name} className="mx-auto max-h-[75vh] object-contain" />
              ) : viewAtt.type === "application/pdf" ? (
                <iframe src={viewAtt.url} title={viewAtt.name} className="h-[75vh] w-full" />
              ) : (
                <div className="p-10 text-center text-sm text-slate-500">
                  Preview not available for this file type.
                  <a href={viewAtt.url} download={viewAtt.name} className="mt-2 block font-bold text-[#357ABD]">Download instead</a>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {showEmail && <SendEmailModal lead={lead} onClose={() => setShowEmail(false)} onSent={() => { setShowEmail(false); reloadMessages(); }} />}
      {showNewTag && <NewTagModal onClose={() => setShowNewTag(false)} onCreated={async (tag) => {
        setShowNewTag(false);
        await refreshCatalogs();
        if (!(lead.tags || []).includes(tag.id)) update({ tags: [...(lead.tags || []), tag.id] });
      }} />}
    </div>
  );
}

/* ---------- typed custom-field rendering (Case 2: field types) ---------- */
function FieldEditor({ type, value, onChange, options, testid }) {
  const common = "hivf-input mt-1 !py-1";
  if (type === "selection") {
    return (
      <select className="hivf-select mt-1 w-full !py-1" value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid}>
        <option value="">—</option>
        {(options || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (type === "boolean") {
    return (
      <label className="mt-1 inline-flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={value === "true" || value === true} onChange={(e) => onChange(e.target.checked ? "true" : "false")} data-testid={testid} />
        Yes
      </label>
    );
  }
  if (type === "text") {
    return <textarea rows={2} className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />;
  }
  if (type === "integer" || type === "float" || type === "monetary") {
    return <input type="number" step={type === "integer" ? "1" : "any"} className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />;
  }
  if (type === "date") return <input type="date" className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />;
  if (type === "datetime") return <input type="datetime-local" className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />;
  return <input className={common} value={value || ""} onChange={(e) => onChange(e.target.value)} data-testid={testid} />;
}

function fieldDisplay(type, value) {
  if (value == null || value === "") return null;
  if (type === "boolean") return value === "true" || value === true ? "Yes" : "No";
  if (type === "monetary") return `₹${value}`;
  return String(value);
}

/* ---------- Meta / Google Q&A (Case 3) ---------- */
function QACard({ lead, onSave, catalogs, labelOf }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const fieldLabels = catalogs?.field_labels || {};
  const customDefs = (catalogs?.custom_fields || []).filter((f) => f.active && f.section === "qa");

  const isQuestion = (k) => {
    const lbl = fieldLabels[k]?.label || "";
    return lbl.includes("?") || /want_to_consult|tried_ivf|trying_to_conceive|treatment_before|health_issues|genetic|sperm_test|working_couple|fertility_treatment/i.test(k);
  };
  const extraQa = Object.entries(lead.custom || {})
    .filter(([k, v]) => isQuestion(k) && v !== null && v !== "")
    .map(([k, v]) => ({ key: k, label: labelOf(k), value: Array.isArray(v) ? v[1] ?? v.join(",") : String(v), field_type: "char", options: [] }));
  const defined = customDefs.map((d) => ({
    key: d.key, label: d.label, value: lead.custom?.[d.key] != null ? String(lead.custom[d.key]) : "",
    field_type: d.field_type || "char", options: d.options || [],
  }));
  const seen = new Set(defined.map((e) => e.key));
  const entries = [...defined, ...extraQa.filter((e) => !seen.has(e.key))];

  if (entries.length === 0) return null;

  const startEdit = () => {
    setDraft(Object.fromEntries(entries.map((e) => [e.key, e.value])));
    setEditing(true);
  };
  const save = () => {
    const changed = {};
    entries.forEach((e) => { if ((draft[e.key] ?? "") !== e.value) changed[e.key] = draft[e.key] || null; });
    if (Object.keys(changed).length) onSave({ custom: changed });
    setEditing(false);
  };

  return (
    <div className="rounded-2xl border-2 border-[#8B5CF6]/25 bg-white p-4" data-testid="qa-card">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm font-extrabold text-[#8B5CF6]">Meta / Google Q&A</h3>
        {editing ? (
          <div className="flex gap-2">
            <button onClick={() => setEditing(false)} className="text-xs font-bold text-slate-400">Cancel</button>
            <button data-testid="qa-save-button" onClick={save} className="text-xs font-bold text-[#357ABD]">Save</button>
          </div>
        ) : (
          <button data-testid="qa-edit-button" onClick={startEdit} className="text-slate-300 hover:text-[#8B5CF6]"><NotePencil size={16} /></button>
        )}
      </div>
      <p className="mb-3 text-[11px] text-slate-400">Answers the customer submitted on the ad / landing page — confirm these on the call.</p>
      <div className="space-y-2">
        {entries.map((e) => (
          <div key={e.key} className="rounded-lg bg-[#8B5CF6]/5 px-3 py-2">
            <p className="text-[11px] font-bold text-slate-500">{e.label}</p>
            {editing ? (
              <FieldEditor type={e.field_type} value={draft[e.key]} options={e.options}
                onChange={(v) => setDraft((d) => ({ ...d, [e.key]: v }))} testid={`qa-input-${e.key}`} />
            ) : (
              <p className="text-sm font-semibold text-slate-800" data-testid={`qa-value-${e.key}`}>{fieldDisplay(e.field_type, e.value) || <span className="text-slate-300">—</span>}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Admin-defined custom fields (Case 4) ---------- */
function CustomFieldsCard({ lead, onSave, catalogs }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const defs = (catalogs?.custom_fields || []).filter((f) => f.active !== false && f.section === "general");
  if (defs.length === 0) return null;

  const valueOf = (d) => (lead.custom?.[d.key] != null ? String(lead.custom[d.key]) : "");
  const startEdit = () => {
    setDraft(Object.fromEntries(defs.map((d) => [d.key, valueOf(d)])));
    setEditing(true);
  };
  const save = () => {
    const changed = {};
    defs.forEach((d) => { if ((draft[d.key] ?? "") !== valueOf(d)) changed[d.key] = draft[d.key] || null; });
    if (Object.keys(changed).length) onSave({ custom: changed });
    setEditing(false);
  };

  return (
    <div className="hivf-card p-4" data-testid="custom-fields-card">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Custom Fields</h3>
        {editing ? (
          <div className="flex gap-2">
            <button onClick={() => setEditing(false)} className="text-xs font-bold text-slate-400">Cancel</button>
            <button data-testid="custom-fields-save-button" onClick={save} className="text-xs font-bold text-[#357ABD]">Save</button>
          </div>
        ) : (
          <button data-testid="custom-fields-edit-button" onClick={startEdit} className="text-slate-300 hover:text-[#4A90E2]"><NotePencil size={16} /></button>
        )}
      </div>
      <div className="space-y-1.5">
        {defs.map((d) => (
          <div key={d.key} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-400">{d.label}</span>
            {editing ? (
              <div className="flex-1"><FieldEditor type={d.field_type} value={draft[d.key]} options={d.options}
                onChange={(v) => setDraft((dr) => ({ ...dr, [d.key]: v }))} testid={`custom-field-input-${d.key}`} /></div>
            ) : (
              <span className="truncate text-slate-700" data-testid={`custom-field-value-${d.key}`}>{fieldDisplay(d.field_type, valueOf(d)) || <span className="text-slate-300">—</span>}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- field card with select support (Cases 1 & 7) ---------- */
function FieldCard({ title, lead, onSave, fields, selects = {}, defaults = {}, required = [] }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [errors, setErrors] = useState({});

  const startEdit = () => {
    setDraft(Object.fromEntries(fields.map(([k]) => [k, lead[k] || defaults[k] || ""])));
    setErrors({});
    setEditing(true);
  };
  const save = () => {
    const errs = {};
    required.forEach((k) => { if (!String(draft[k] || "").trim()) errs[k] = "This field is required"; });
    if (Object.keys(errs).length) { setErrors(errs); toast.error("Please fill the required field(s)"); return; }
    setErrors({});
    const updates = {};
    fields.forEach(([k]) => { if ((draft[k] || "") !== (lead[k] || "")) updates[k] = draft[k] || null; });
    if (Object.keys(updates).length) onSave(updates);
    setEditing(false);
  };

  return (
    <div className="hivf-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm font-extrabold text-slate-800">{title}</h3>
        {editing ? (
          <div className="flex gap-2">
            <button onClick={() => setEditing(false)} className="text-xs font-bold text-slate-400">Cancel</button>
            <button data-testid={`save-${title.toLowerCase().replace(/\s/g, "-")}`} onClick={save} className="text-xs font-bold text-[#357ABD]">Save</button>
          </div>
        ) : (
          <button data-testid={`edit-${title.toLowerCase().replace(/\s/g, "-")}`} onClick={startEdit} className="text-slate-300 hover:text-[#4A90E2]"><NotePencil size={16} /></button>
        )}
      </div>
      <div className="space-y-1.5">
        {fields.map(([k, label, type]) => (
          <div key={k} className="flex items-start gap-2 text-sm">
            <span className="mt-1 w-28 shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-400">
              {label}{required.includes(k) && <span className="text-rose-500"> *</span>}
            </span>
            {editing ? (
              <div className="flex-1">
                {type === "select" && selects[k] ? (
                  <select className={`hivf-select w-full !py-1 ${errors[k] ? "!border-rose-400" : ""}`} value={draft[k] || defaults[k] || ""} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} data-testid={`field-input-${k}`}>
                    <option value="">—</option>
                    {draft[k] && !selects[k].includes(draft[k]) && <option value={draft[k]}>{draft[k]}</option>}
                    {selects[k].map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input className={`hivf-input !py-1 ${errors[k] ? "!border-rose-400" : ""}`} value={draft[k] || ""} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} data-testid={`field-input-${k}`} />
                )}
                {errors[k] && <p className="mt-0.5 text-[10px] font-semibold text-rose-500" data-testid={`field-error-${k}`}>{errors[k]}</p>}
              </div>
            ) : (
              <span className="truncate text-slate-700" data-testid={`field-value-${k}`}>{lead[k] || defaults[k] || <span className="text-slate-300">—</span>}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Send WhatsApp template (Case 5) ---------- */
function SendWhatsAppModal({ lead, onClose, onSent }) {
  const [templates, setTemplates] = useState(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [phone, setPhone] = useState(lead.phone || lead.mobile || "");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    API.get("/templates/whatsapp").then(({ data }) => setTemplates(data.filter((t) => t.active !== false)));
  }, []);

  const filtered = (templates || []).filter((t) => t.name.toLowerCase().includes(search.toLowerCase()));
  const preview = selected ? (selected.body || "").replace("{{1}}", lead.contact_name || lead.name || "") : "";

  const send = async () => {
    if (!selected) return toast.error("Choose a template");
    setSending(true);
    try {
      await API.post(`/leads/${lead.id}/send_whatsapp`, { template_id: selected.id, phone });
      toast.success(`Queued '${selected.name}' to ${phone} — sends when WhatsApp API is connected`);
      onSent();
    } catch (e) { toast.error(apiErr(e)); } finally { setSending(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl bg-white p-6 shadow-xl" data-testid="send-whatsapp-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900"><WhatsappLogo size={20} className="mr-1 inline text-emerald-500" weight="duotone" />Send WhatsApp Message</h3>
        <div className="mt-3 space-y-3 overflow-y-auto">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Phone</label>
            <input data-testid="wa-phone-input" className="hivf-input mt-1" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Template</label>
            <input data-testid="wa-template-search" className="hivf-input mt-1" placeholder="Search templates…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="mt-2 max-h-44 space-y-1 overflow-y-auto rounded-xl border border-slate-100 p-2" data-testid="wa-template-list">
              {templates === null ? <Spinner /> : filtered.map((t) => (
                <button key={t.id} data-testid={`wa-template-option-${t.id}`} onClick={() => setSelected(t)}
                  className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${selected?.id === t.id ? "bg-emerald-50 font-bold text-emerald-700" : "hover:bg-slate-50 text-slate-600"}`}>
                  <span className="truncate">{t.name}</span>
                  {t.status && <span className={`ml-2 shrink-0 rounded-full px-1.5 text-[9px] font-bold ${t.status === "approved" ? "bg-emerald-100 text-emerald-600" : "bg-amber-100 text-amber-600"}`}>{t.status}</span>}
                </button>
              ))}
              {templates !== null && filtered.length === 0 && <p className="py-3 text-center text-xs text-slate-400">No templates match</p>}
            </div>
          </div>
          {selected && (
            <div className="rounded-xl bg-emerald-50/60 p-3" data-testid="wa-preview">
              <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-600">Preview</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{preview}</p>
            </div>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button data-testid="wa-send-submit" onClick={send} disabled={sending || !selected}
            className="inline-flex items-center gap-2 rounded-full bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-600 disabled:opacity-50">
            <PaperPlaneTilt size={15} /> {sending ? "Queuing…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Compose Email (Case 6) ---------- */
function SendEmailModal({ lead, onClose, onSent }) {
  const [templates, setTemplates] = useState([]);
  const [to, setTo] = useState(lead.email_from || "");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [saveAs, setSaveAs] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    API.get("/templates/email").then(({ data }) => setTemplates(data.filter((t) => t.active !== false)));
  }, []);

  const applyTemplate = (id) => {
    const t = templates.find((x) => x.id === parseInt(id));
    if (!t) return;
    setSubject((t.subject || t.name || "").replace(/\{\{.*?\}\}/g, lead.contact_name || ""));
    setBody(t.body || "");
  };

  const send = async () => {
    if (!subject.trim() || !body.trim()) return toast.error("Subject and body are required");
    setSending(true);
    try {
      await API.post(`/leads/${lead.id}/send_email`, {
        to, subject: subject.trim(), body,
        save_as_template: saveAs && saveName.trim() ? saveName.trim() : null,
      });
      toast.success(`Email queued to ${to} — sends when SMTP is connected`);
      onSent();
    } catch (e) { toast.error(apiErr(e)); } finally { setSending(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-2xl bg-white p-6 shadow-xl" data-testid="send-email-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900"><EnvelopeSimple size={20} className="mr-1 inline text-[#4A90E2]" weight="duotone" />Compose Email</h3>
        <div className="mt-3 space-y-3 overflow-y-auto">
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">To</label>
              <input data-testid="email-to-input" className="hivf-input mt-1" value={to} onChange={(e) => setTo(e.target.value)} placeholder="customer@email.com" />
            </div>
            <div className="flex-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Select a template</label>
              <select data-testid="email-template-select" className="hivf-select mt-1 w-full" value="" onChange={(e) => e.target.value && applyTemplate(e.target.value)}>
                <option value="">Choose…</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Subject</label>
            <input data-testid="email-subject-input" className="hivf-input mt-1" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Body (HTML supported)</label>
            <textarea data-testid="email-body-input" rows={8} className="hivf-input mt-1 font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
          {body && (
            <details className="rounded-xl border border-slate-100 p-3">
              <summary className="cursor-pointer text-xs font-bold text-slate-500">Preview</summary>
              <div className="chatter-body mt-2 max-h-48 overflow-y-auto text-sm text-slate-700" dangerouslySetInnerHTML={{ __html: body }} />
            </details>
          )}
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <input type="checkbox" data-testid="email-save-template-checkbox" checked={saveAs} onChange={(e) => setSaveAs(e.target.checked)} />
            Save as template
            {saveAs && <input className="hivf-input !w-56 !py-1" placeholder="Template name" value={saveName} onChange={(e) => setSaveName(e.target.value)} data-testid="email-save-template-name" />}
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="hivf-btn-secondary">Discard</button>
          <button data-testid="email-send-submit" onClick={send} disabled={sending} className="hivf-btn-primary">
            <PaperPlaneTilt size={15} /> {sending ? "Queuing…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- New tag popup (Case 2) ---------- */
function NewTagModal({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      const { data } = await API.post("/catalogs/tag", { name: name.trim(), color: Math.floor(Math.random() * 11) + 1 });
      toast.success(`Tag '${data.name}' ready`);
      onCreated(data);
    } catch (err) { toast.error(apiErr(err)); } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-xs rounded-2xl bg-white p-6 shadow-xl" data-testid="new-tag-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900">New Disposition Tag</h3>
        <input data-testid="new-tag-name-input" autoFocus required className="hivf-input mt-4" placeholder="Tag name" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button data-testid="new-tag-submit" type="submit" disabled={saving} className="hivf-btn-primary">{saving ? "Creating…" : "Create & Add"}</button>
        </div>
      </form>
    </div>
  );
}

function WaLeadPanel({ leadId }) {
  const navigate = useNavigate();
  const { checkAllowed } = useNavGuard();
  const [items, setItems] = useState(null);
  useEffect(() => { API.get(`/wa/lead/${leadId}/messages`).then(({ data }) => setItems(data)).catch(() => setItems([])); }, [leadId]);
  if (!items || items.length === 0) return null;
  return (
    <div className="hivf-card p-4" data-testid="wa-lead-panel">
      <div className="mb-2 flex items-center gap-2">
        <WhatsappLogo size={16} weight="fill" className="text-[#25D366]" />
        <h3 className="font-display text-sm font-extrabold text-slate-800">WhatsApp Messages</h3>
      </div>
      <div className="space-y-2">
        {items.map((m) => {
          const meta = waMeta(m.status);
          return (
            <div key={m.id} onClick={() => { if (checkAllowed()) navigate(`/wa/message/${m.id}`); }} data-testid={`wa-lead-msg-${m.id}`}
              className="cursor-pointer rounded-xl border border-slate-100 p-2.5 transition-colors hover:bg-[#25D366]/5">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-xs font-bold text-slate-700">{m.template_name}</p>
                <span title={`Status: ${meta.label}`} className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${meta.cls}`} data-testid={`wa-lead-msg-status-${m.id}`}>{meta.label}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{m.body}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TemplateActivityPreview({ m, liveStatus, navigate }) {
  const { checkAllowed } = useNavGuard();
  const status = liveStatus || m.status || "in_queue";
  const meta = waMeta(status);
  const isWa = m.kind === "wa_template";
  const clickable = isWa && m.track_id;
  return (
    <div className={`mt-2 rounded-xl border p-2.5 ${isWa ? "border-[#25D366]/25 bg-[#dcf8c6]/30" : "border-indigo-100 bg-indigo-50/40"} ${clickable ? "cursor-pointer transition-colors hover:brightness-95" : ""}`}
      data-testid={`activity-preview-${m.id}`}
      onClick={() => { if (clickable && checkAllowed()) navigate(`/wa/message/${m.track_id}`); }}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1 truncate text-[11px] font-bold text-slate-600">
          {isWa ? <WhatsappLogo size={13} weight="fill" className="text-[#25D366]" /> : <EnvelopeSimple size={13} className="text-indigo-500" />}
          {m.template_name}
        </p>
        <span title={`Status: ${meta.label}`} data-testid={`activity-status-${m.id}`}
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${meta.cls}`}>{meta.label}</span>
      </div>
      {isWa ? (
        <p className="whitespace-pre-wrap text-[12px] text-slate-700">{m.preview}</p>
      ) : (
        <div className="chatter-body max-h-32 overflow-auto text-[12px] text-slate-600" dangerouslySetInnerHTML={{ __html: m.preview || "" }} />
      )}
    </div>
  );
}

function FollowUpSection({ leadId, catalogs, onChanged, onCount }) {
  const [items, setItems] = useState(null);
  const [form, setForm] = useState({ follow_up_date: "", follow_up_time: "", follow_up_tag: "", note: "", status: "" });
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState({});

  const load = () => API.get(`/leads/${leadId}/followups`).then(({ data }) => { setItems(data); onCount && onCount(data.length); });
  useEffect(() => { load(); }, [leadId]);

  const add = async () => {
    if (!form.note.trim()) { toast.error("Note is required for every follow-up"); return; }
    try {
      await API.post(`/leads/${leadId}/followups`, form);
      setForm({ follow_up_date: "", follow_up_time: "", follow_up_tag: "", note: "", status: "" });
      toast.success("Follow-up added");
      load(); onChanged && onChanged();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const startEdit = (f) => { setEditId(f.id); setEdit({ follow_up_date: f.follow_up_date || "", follow_up_time: f.follow_up_time || "", follow_up_tag: f.follow_up_tag || "", note: f.note || "", status: f.status || "" }); };
  const saveEdit = async (fid) => {
    if (!edit.note.trim()) { toast.error("Note is required"); return; }
    try {
      await API.patch(`/leads/${leadId}/followups/${fid}`, edit);
      setEditId(null); toast.success("Follow-up updated");
      load(); onChanged && onChanged();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const setStatus = async (fid, status) => {
    try {
      await API.post(`/leads/${leadId}/followups/${fid}/status`, { status });
      toast.success(status ? `Marked ${status}` : "Status cleared");
      load(); onChanged && onChanged();
    } catch (e) { toast.error(apiErr(e)); }
  };
  const del = async (fid) => {
    if (!window.confirm("Delete this follow-up entry?")) return;
    try { await API.delete(`/leads/${leadId}/followups/${fid}`); toast.success("Deleted"); load(); onChanged && onChanged(); }
    catch (e) { toast.error(apiErr(e)); }
  };

  const tagOptions = catalogs?.follow_up_tag || [];
  const statusOptions = (catalogs?.followup_status || []).filter((s) => s.active !== false);
  const statusTone = (s) => ({ Completed: "bg-emerald-50 text-emerald-600", Rescheduled: "bg-amber-50 text-amber-600", Cancelled: "bg-slate-100 text-slate-500" }[s] || "bg-[#4A90E2]/10 text-[#357ABD]");

  return (
    <div className="mt-4" data-testid="followup-section">
      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3">
        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Add a follow-up</label>
        <div className="mt-1 grid grid-cols-2 gap-2">
          <input data-testid="followup-add-date" type="date" className="hivf-select" value={form.follow_up_date} onChange={(e) => setForm((f) => ({ ...f, follow_up_date: e.target.value }))} />
          <input data-testid="followup-add-time" type="time" className="hivf-select" value={form.follow_up_time} onChange={(e) => setForm((f) => ({ ...f, follow_up_time: e.target.value }))} />
          <select data-testid="followup-add-tag" className="hivf-select" value={form.follow_up_tag} onChange={(e) => setForm((f) => ({ ...f, follow_up_tag: e.target.value }))}>
            <option value="">Follow-up tag (optional)…</option>
            {tagOptions.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
          </select>
          <select data-testid="followup-add-status" className="hivf-select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
            <option value="">Status (optional)…</option>
            {statusOptions.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <textarea data-testid="followup-add-note" rows={2} className="hivf-input col-span-2" placeholder="Note * (what happened on the call)" value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
        </div>
        <button data-testid="followup-add-button" onClick={add} className="hivf-btn-primary mt-2 !py-1.5 text-xs"><Plus size={13} /> Add follow-up</button>
      </div>

      <div className="mt-3 space-y-2" data-testid="followup-list">
        {items === null ? <div className="text-xs text-slate-400">Loading…</div>
          : items.length === 0 ? <p className="text-xs text-slate-400" data-testid="followup-empty">No follow-ups scheduled yet.</p>
          : items.map((f) => (
            <div key={f.id} className="rounded-xl border border-slate-100 p-2.5" data-testid={`followup-item-${f.id}`}>
              {editId === f.id ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <input type="date" className="hivf-select" value={edit.follow_up_date} onChange={(e) => setEdit((d) => ({ ...d, follow_up_date: e.target.value }))} data-testid={`followup-edit-date-${f.id}`} />
                    <input type="time" className="hivf-select" value={edit.follow_up_time} onChange={(e) => setEdit((d) => ({ ...d, follow_up_time: e.target.value }))} />
                    <select className="hivf-select" value={edit.follow_up_tag} onChange={(e) => setEdit((d) => ({ ...d, follow_up_tag: e.target.value }))}>
                      <option value="">Follow-up tag…</option>
                      {tagOptions.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
                    </select>
                    <select className="hivf-select" value={edit.status} onChange={(e) => setEdit((d) => ({ ...d, status: e.target.value }))} data-testid={`followup-edit-status-${f.id}`}>
                      <option value="">Status…</option>
                      {statusOptions.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                    </select>
                    <textarea className="hivf-input col-span-2" rows={2} placeholder="Note *" value={edit.note} onChange={(e) => setEdit((d) => ({ ...d, note: e.target.value }))} />
                  </div>
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setEditId(null)} className="text-xs font-bold text-slate-400">Cancel</button>
                    <button onClick={() => saveEdit(f.id)} className="text-xs font-bold text-[#357ABD]" data-testid={`followup-save-${f.id}`}>Save</button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-2">
                  <CalendarCheck size={16} className="mt-0.5 shrink-0 text-[#4A90E2]" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-slate-700">
                      {f.follow_up_date ? fmtDay(f.follow_up_date) : "No date"}{f.follow_up_time ? ` · ${f.follow_up_time}` : ""}
                      {f.follow_up_tag ? <span className="ml-2 rounded-full bg-[#4A90E2]/10 px-2 py-0.5 text-[10px] font-bold text-[#357ABD]">{f.follow_up_tag}</span> : null}
                      {f.status ? <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold ${statusTone(f.status)}`} data-testid={`followup-status-badge-${f.id}`}>{f.status}</span> : null}
                    </p>
                    {f.note && <p className="text-xs text-slate-500">{f.note}</p>}
                    <p className="text-[10px] text-slate-400">{f.created_by_name} · {fmtDate(f.created_at)}</p>
                    <select value={f.status || ""} onChange={(e) => setStatus(f.id, e.target.value)} data-testid={`followup-set-status-${f.id}`}
                      className="mt-1.5 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                      <option value="">Set status…</option>
                      {statusOptions.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                    </select>
                  </div>
                  <button onClick={() => startEdit(f)} className="text-slate-300 hover:text-[#4A90E2]" data-testid={`followup-edit-${f.id}`} title="Edit"><NotePencil size={15} /></button>
                  <button onClick={() => del(f.id)} className="text-slate-300 hover:text-rose-500" data-testid={`followup-delete-${f.id}`} title="Delete"><Trash size={15} /></button>
                </div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}

function CallerActivities({ leadId, onCount }) {
  const [items, setItems] = useState(null);
  const [feedback, setFeedback] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => API.get(`/leads/${leadId}/caller-activities`).then(({ data }) => {
    setItems(data);
    onCount && onCount(data.length);
  });
  useEffect(() => { load(); }, [leadId]);

  const add = async () => {
    if (!feedback.trim()) { toast.error("Enter a feedback note"); return; }
    setSaving(true);
    try {
      await API.post(`/leads/${leadId}/caller-activities`, { feedback: feedback.trim() });
      setFeedback("");
      toast.success("Caller activity added");
      load();
    } catch (e) { toast.error(apiErr(e)); } finally { setSaving(false); }
  };

  return (
    <div className="hivf-card p-4" data-testid="caller-activities-section">
      <h3 className="mb-1 font-display text-sm font-extrabold text-slate-800">Caller Activities</h3>
      <p className="mb-3 text-[11px] text-slate-400">Log what happened on each call so any teammate can read the history before calling again.</p>
      <textarea data-testid="caller-activity-input" rows={2} className="hivf-input" placeholder="Customer / call feedback…" value={feedback} onChange={(e) => setFeedback(e.target.value)} />
      <button data-testid="caller-activity-add" onClick={add} disabled={saving} className="hivf-btn-primary mt-2 !py-1.5 text-xs"><Plus size={13} /> Add More Note</button>

      <div className="mt-3 space-y-2" data-testid="caller-activity-list">
        {items === null ? <div className="text-xs text-slate-400">Loading…</div>
          : items.length === 0 ? <p className="text-xs text-slate-400" data-testid="caller-activity-empty">No caller activities yet.</p>
          : items.map((a) => (
            <div key={a.id} className="rounded-xl border border-slate-100 bg-slate-50/60 p-2.5" data-testid={`caller-activity-${a.id}`}>
              <p className="text-sm text-slate-700 whitespace-pre-wrap">{a.feedback}</p>
              <p className="mt-1 text-[10px] font-semibold text-slate-400">{a.created_by_name} · {fmtDate(a.created_at)}</p>
            </div>
          ))}
      </div>
    </div>
  );
}

function ActivityModal({ leadId, onClose, onSaved, catalogs }) {
  const [form, setForm] = useState({ type_name: "Call", summary: "", date_deadline: todayStr() });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await API.post(`/leads/${leadId}/activities`, form);
      toast.success("Activity scheduled");
      onSaved();
    } catch (err) { toast.error(apiErr(err)); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl" data-testid="activity-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900">Schedule Activity</h3>
        <div className="mt-4 space-y-3">
          <select className="hivf-select w-full" value={form.type_name} onChange={(e) => setForm((f) => ({ ...f, type_name: e.target.value }))} data-testid="activity-type-select">
            {(catalogs?.activity_type?.length ? catalogs.activity_type.map((t) => t.name) : ["Call", "To-Do", "Email", "Meeting"]).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input className="hivf-input" placeholder="Summary" value={form.summary} onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))} data-testid="activity-summary-input" />
          <input type="date" required className="hivf-input" value={form.date_deadline} onChange={(e) => setForm((f) => ({ ...f, date_deadline: e.target.value }))} data-testid="activity-date-input" />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button type="submit" className="hivf-btn-primary" data-testid="activity-submit">Schedule</button>
        </div>
      </form>
    </div>
  );
}

function LostModal({ leadId, onClose, onSaved, catalogs }) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      await API.post(`/leads/${leadId}/lost`, { lost_reason_id: reason ? parseInt(reason) : null, note: note || null });
      toast.success("Marked as lost");
      onSaved();
    } catch (err) { toast.error(apiErr(err)); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl" data-testid="lost-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900">Mark Lead as Lost</h3>
        <div className="mt-4 space-y-3">
          <select className="hivf-select w-full" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="lost-reason-select">
            <option value="">Select reason…</option>
            {(catalogs?.lost_reason || []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <textarea className="hivf-input" rows={2} placeholder="Closing note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button type="submit" className="hivf-btn-primary !bg-rose-500 hover:!bg-rose-600" data-testid="lost-submit">Mark Lost</button>
        </div>
      </form>
    </div>
  );
}
