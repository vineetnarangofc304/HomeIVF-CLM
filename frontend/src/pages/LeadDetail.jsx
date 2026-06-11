import React, { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, NotePencil, PaperPlaneTilt, Phone, EnvelopeSimple, MapPin,
  CalendarCheck, Sparkle, Prohibit, ArrowCounterClockwise, WhatsappLogo, CheckCircle, XCircle, Plus,
} from "@phosphor-icons/react";
import { API, apiErr, fmtDate, fmtDay, todayStr } from "../lib/api";
import { useAuth, useCatalogMaps } from "../context/AuthContext";
import { TagChip, Spinner, EmptyState } from "../components/Bits";

export default function LeadDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { catalogs, tagById, userById, lostById } = useCatalogMaps();
  const [lead, setLead] = useState(null);
  const [messages, setMessages] = useState([]);
  const [msgTotal, setMsgTotal] = useState(0);
  const [msgPage, setMsgPage] = useState(1);
  const [activities, setActivities] = useState([]);
  const [waChannels, setWaChannels] = useState([]);
  const [tab, setTab] = useState("chatter");
  const [note, setNote] = useState("");
  const [showActivity, setShowActivity] = useState(false);
  const [showLost, setShowLost] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ data: l }, { data: m }, { data: a }, { data: w }] = await Promise.all([
        API.get(`/leads/${id}`),
        API.get(`/leads/${id}/messages`, { params: { page: 1 } }),
        API.get(`/leads/${id}/activities`),
        API.get(`/whatsapp/lead/${id}`),
      ]);
      setLead(l);
      setMessages(m.items);
      setMsgTotal(m.total);
      setMsgPage(1);
      setActivities(a);
      setWaChannels(w);
    } catch (e) {
      toast.error(apiErr(e));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const update = async (updates) => {
    try {
      const { data } = await API.patch(`/leads/${id}`, { updates });
      setLead(data);
      const { data: m } = await API.get(`/leads/${id}/messages`, { params: { page: 1 } });
      setMessages(m.items); setMsgTotal(m.total); setMsgPage(1);
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

  if (!lead) return <Spinner />;

  const leadStages = (catalogs?.lead_stage || []).map((s) => s.name);

  return (
    <div className="h-full overflow-y-auto" data-testid="lead-detail-page">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <button data-testid="back-button" onClick={() => navigate(-1)} className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100"><ArrowLeft size={18} /></button>
          <div className="mr-auto">
            <h1 className="font-display text-lg font-extrabold text-slate-900" data-testid="lead-name">{lead.contact_name || lead.name}</h1>
            <p className="text-xs text-slate-500">#{lead.id} · created {fmtDate(lead.create_date)} {!lead.active && <span className="ml-1 font-bold uppercase text-rose-500">Lost{lead.lost_reason_id ? ` — ${lostById[lead.lost_reason_id]?.name || ""}` : ""}</span>}</p>
          </div>
          {/* Lead stage stepper */}
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

      <div className="grid grid-cols-1 gap-5 p-5 lg:grid-cols-5">
        {/* LEFT: fields */}
        <div className="space-y-4 lg:col-span-2">
          {/* AI hook */}
          <div className="rounded-2xl border border-[#8B5CF6]/20 bg-gradient-to-br from-[#8B5CF6]/5 to-[#4A90E2]/5 p-4">
            <div className="flex items-center gap-2 text-[#8B5CF6]"><Sparkle size={15} weight="fill" /><span className="text-xs font-bold">AI Summary</span></div>
            <p className="mt-1 text-xs text-slate-500">AI insights & next-best-action arrive in Phase 2.</p>
          </div>

          <FieldCard title="Contact" lead={lead} onSave={update} fields={[
            ["contact_name", "Name"], ["phone", "Phone"], ["email_from", "Email"],
            ["city", "City"], ["state_name", "State"],
          ]} icons={{ phone: Phone, email_from: EnvelopeSimple, city: MapPin }} />

          <FieldCard title="Case Details" lead={lead} onSave={update} fields={[
            ["gender", "Gender"], ["age", "Age"], ["male_age", "Male Age"], ["female_age", "Female Age"],
            ["spouse_name", "Spouse Name"], ["spouse_age", "Spouse Age"], ["pre_conditions", "Pre-conditions"],
            ["doctor_name", "Doctor"], ["query", "Query"], ["remark", "Remark"],
          ]} />

          {/* Assignment & follow-up */}
          <div className="hivf-card p-4">
            <h3 className="mb-3 font-display text-sm font-extrabold text-slate-800">Assignment & Follow-up</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Caller</label>
                <select data-testid="assignee-select" disabled={user.role === "caller"} className="hivf-select mt-1 w-full" value={lead.user_id || ""} onChange={(e) => update({ user_id: e.target.value ? parseInt(e.target.value) : null })}>
                  <option value="">Unassigned</option>
                  {(catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Follow-up Tag</label>
                <select data-testid="followup-tag-select" className="hivf-select mt-1 w-full" value={lead.follow_up_tag || ""} onChange={(e) => update({ follow_up_tag: e.target.value || null })}>
                  <option value="">None</option>
                  {(catalogs?.follow_up_tag || []).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Follow-up Date</label>
                <input data-testid="followup-date-input" type="date" className="hivf-select mt-1 w-full" value={lead.follow_up_date || ""} onChange={(e) => update({ follow_up_date: e.target.value || null })} />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Appointment</label>
                <input data-testid="appointment-date-input" type="date" className="hivf-select mt-1 w-full" value={lead.appointment_date || ""} onChange={(e) => update({ appointment_date: e.target.value || null })} />
              </div>
            </div>
          </div>

          {/* Tags */}
          <div className="hivf-card p-4">
            <h3 className="mb-2 font-display text-sm font-extrabold text-slate-800">Disposition Tags</h3>
            <div className="flex flex-wrap gap-1.5" data-testid="lead-tags">
              {(lead.tags || []).map((t) => (
                <TagChip key={t} tag={tagById[t]} onRemove={() => update({ tags: lead.tags.filter((x) => x !== t) })} />
              ))}
            </div>
            <select data-testid="add-tag-select" className="hivf-select mt-3 w-full" value=""
              onChange={(e) => { const v = parseInt(e.target.value); if (v && !(lead.tags || []).includes(v)) update({ tags: [...(lead.tags || []), v] }); }}>
              <option value="">+ Add disposition tag…</option>
              {(catalogs?.tag || []).filter((t) => t.active !== false && !(lead.tags || []).includes(t.id)).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>

          <FieldCard title="Attribution" lead={lead} onSave={update} fields={[
            ["source_lead", "Source"], ["ads_platform", "Ads Platform"], ["campaign_name", "Campaign"],
            ["ads_campaign_name", "Ads Campaign"], ["ads_name", "Ad Name"],
          ]} extra={[["Medium", lead.medium_id], ["UTM Source", lead.source_id], ["UTM Campaign", lead.campaign_id]]} />

          {/* Raw odoo fields */}
          {lead.custom && Object.keys(lead.custom).length > 0 && (
            <details className="hivf-card p-4">
              <summary className="cursor-pointer font-display text-sm font-extrabold text-slate-800">All Odoo fields ({Object.keys(lead.custom).length})</summary>
              <div className="mt-3 max-h-72 space-y-1 overflow-y-auto text-xs">
                {Object.entries(lead.custom).map(([k, v]) => (
                  <div key={k} className="flex gap-2 border-b border-slate-50 py-1">
                    <span className="w-1/2 shrink-0 truncate font-semibold text-slate-500" title={k}>{k.replace("x_studio_", "")}</span>
                    <span className="text-slate-700">{Array.isArray(v) ? v[1] ?? v.join(",") : String(v)}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* RIGHT: chatter */}
        <div className="lg:col-span-3">
          <div className="hivf-card">
            <div className="flex items-center gap-1 border-b border-slate-100 px-4 pt-3">
              {[["chatter", "Chatter", msgTotal], ["activities", "Activities", activities.length], ["whatsapp", "WhatsApp", waChannels.length]].map(([k, l, c]) => (
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
                    <div key={m.id} className={`rounded-xl border p-3 ${m.subtype === "note" ? "border-amber-100 bg-amber-50/50" : m.subtype === "comment" ? "border-blue-100 bg-blue-50/40" : "border-slate-100 bg-white"}`}>
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-700">{m.author_name || "System"}</span>
                        <span className="text-[11px] text-slate-400">{fmtDate(m.date)}</span>
                      </div>
                      {m.subject && <p className="text-xs font-semibold text-slate-600">{m.subject}</p>}
                      <div className="chatter-body text-sm text-slate-700" dangerouslySetInnerHTML={{ __html: m.body }} />
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
          </div>
        </div>
      </div>

      {showActivity && <ActivityModal leadId={lead.id} onClose={() => setShowActivity(false)} onSaved={() => { setShowActivity(false); load(); }} catalogs={catalogs} />}
      {showLost && <LostModal leadId={lead.id} onClose={() => setShowLost(false)} onSaved={() => { setShowLost(false); load(); }} catalogs={catalogs} />}
    </div>
  );
}

function FieldCard({ title, lead, onSave, fields, extra = [] }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});

  const startEdit = () => {
    setDraft(Object.fromEntries(fields.map(([k]) => [k, lead[k] || ""])));
    setEditing(true);
  };
  const save = () => {
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
        {fields.map(([k, label]) => (
          <div key={k} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
            {editing ? (
              <input className="hivf-input !py-1" value={draft[k] || ""} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} data-testid={`field-input-${k}`} />
            ) : (
              <span className="truncate text-slate-700" data-testid={`field-value-${k}`}>{lead[k] || <span className="text-slate-300">—</span>}</span>
            )}
          </div>
        ))}
        {extra.map(([label, val]) => val && (
          <div key={label} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
            <span className="truncate text-slate-500">{val}</span>
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
