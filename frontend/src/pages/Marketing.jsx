import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Plus, Trash, PaperPlaneTilt, WhatsappLogo, EnvelopeSimple, Users, Megaphone,
  Pause, PencilSimple, Eye, ArrowClockwise, WarningCircle, CheckCircle, ChatCircleDots,
} from "@phosphor-icons/react";
import { API, apiErr, fmtDate } from "../lib/api";
import { useCatalogs } from "../context/AuthContext";
import { Spinner, EmptyState } from "../components/Bits";

const STATUS_BADGE = {
  draft: "bg-slate-100 text-slate-500",
  in_progress: "bg-amber-50 text-amber-600",
  sending: "bg-amber-50 text-amber-600",
  paused: "bg-orange-50 text-orange-600",
  completed: "bg-emerald-50 text-emerald-600",
  sent: "bg-emerald-50 text-emerald-600",
  partial: "bg-indigo-50 text-indigo-600",
  queued: "bg-sky-50 text-sky-600",
  failed: "bg-rose-50 text-rose-600",
};
const STATUS_LABEL = {
  draft: "Draft", in_progress: "In Progress", sending: "In Progress", paused: "Paused",
  completed: "Completed", sent: "Completed", partial: "Partial", queued: "Queued", failed: "Failed",
};

export default function Marketing() {
  const [campaigns, setCampaigns] = useState(null);
  const [show, setShow] = useState(false);
  const [editing, setEditing] = useState(null);
  const [failuresOf, setFailuresOf] = useState(null);
  const pollRef = useRef(null);

  const load = () => API.get("/marketing/campaigns").then(({ data }) => setCampaigns(data));
  useEffect(() => { load(); }, []);

  // Poll while any campaign is actively sending, so the progress bar animates live.
  useEffect(() => {
    const active = (campaigns || []).some((c) => c.status === "in_progress" || c.status === "sending");
    clearInterval(pollRef.current);
    if (active) pollRef.current = setInterval(load, 3000);
    return () => clearInterval(pollRef.current);
  }, [campaigns]);

  const send = async (c) => {
    if (!c.template_id) { toast.error("Attach a template before sending"); return; }
    const resume = c.status === "paused";
    if (!resume && !window.confirm(`Send "${c.name}" to the matched audience now?`)) return;
    try {
      const { data } = await API.post(`/marketing/campaigns/${c.id}/send`);
      toast.success(resume ? `Resuming "${c.name}"…` : `Sending "${c.name}" to ${data.total} recipients…`);
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  const pause = async (c) => {
    try { await API.post(`/marketing/campaigns/${c.id}/pause`); toast.success("Campaign paused"); load(); }
    catch (e) { toast.error(apiErr(e)); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this campaign?")) return;
    await API.delete(`/marketing/campaigns/${id}`);
    load();
  };

  return (
    <div className="p-6" data-testid="marketing-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-slate-900">Marketing Campaigns</h1>
          <p className="mt-1 text-sm text-slate-500">Create and send bulk WhatsApp & Email campaigns to a targeted audience.</p>
        </div>
        <button data-testid="new-campaign-button" onClick={() => { setEditing(null); setShow(true); }} className="hivf-btn-primary"><Plus size={15} /> New Campaign</button>
      </div>

      {!campaigns ? <Spinner /> : campaigns.length === 0 ? (
        <div className="mt-6"><EmptyState title="No campaigns yet" subtitle="Create your first bulk WhatsApp or Email campaign" /></div>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="campaigns-grid">
          {campaigns.map((c) => (
            <CampaignCard key={c.id} c={c}
              onSend={() => send(c)} onPause={() => pause(c)} onDelete={() => remove(c.id)}
              onEdit={() => { setEditing(c); setShow(true); }} onFailures={() => setFailuresOf(c)} />
          ))}
        </div>
      )}

      {show && <CampaignModal editing={editing} onClose={() => { setShow(false); setEditing(null); }} onSaved={() => { setShow(false); setEditing(null); load(); }} />}
      {failuresOf && <FailuresModal campaign={failuresOf} onClose={() => setFailuresOf(null)} />}
    </div>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div data-testid={`campaign-stat-${label.toLowerCase()}`}>
      <p className={`font-display text-base font-extrabold ${tone || "text-slate-800"}`}>{value ?? 0}</p>
      <p className="text-[10px] uppercase tracking-wider text-slate-400">{label}</p>
    </div>
  );
}

function CampaignCard({ c, onSend, onPause, onDelete, onEdit, onFailures }) {
  const running = c.status === "in_progress" || c.status === "sending";
  const isWa = c.channel === "whatsapp";
  const progress = c.progress ?? 0;
  return (
    <div className="hivf-card flex flex-col p-4" data-testid={`campaign-card-${c.id}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {isWa ? <WhatsappLogo size={18} className="text-emerald-500" /> : <EnvelopeSimple size={18} className="text-[#357ABD]" />}
          <p className="text-sm font-bold text-slate-800">{c.name}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATUS_BADGE[c.status] || "bg-slate-100 text-slate-500"}`} data-testid={`campaign-status-${c.id}`}>{STATUS_LABEL[c.status] || c.status}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="rounded-md bg-slate-50 px-1.5 py-0.5 font-semibold text-slate-500">{isWa ? "WhatsApp" : "Email"}</span>
        {c.template_name && <span className="rounded-md bg-slate-50 px-1.5 py-0.5 font-semibold text-slate-500">Template: {c.template_name}</span>}
      </div>
      <p className="mt-1.5 text-[11px] text-slate-400"><span className="font-semibold text-slate-500">Trigger:</span> {c.trigger_desc || "All active leads"}</p>

      {/* Progress bar */}
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[10px] font-semibold text-slate-400">
          <span>Progress</span><span data-testid={`campaign-progress-${c.id}`}>{progress}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div className={`h-full rounded-full transition-all duration-500 ${c.status === "failed" ? "bg-rose-400" : c.status === "paused" ? "bg-orange-400" : "bg-emerald-400"}`} style={{ width: `${progress}%` }} />
        </div>
      </div>

      {/* Metrics */}
      <div className={`mt-3 grid gap-1 text-center ${isWa ? "grid-cols-4" : "grid-cols-4"}`}>
        <Stat label="Total" value={c.total} />
        <Stat label="Sent" value={c.sent} tone="text-emerald-600" />
        {isWa && <Stat label="Delivered" value={c.delivered} tone="text-sky-600" />}
        {isWa && <Stat label="Read" value={c.read} tone="text-indigo-600" />}
        {!isWa && <Stat label="Queued" value={c.queued} tone="text-sky-600" />}
        {!isWa && <Stat label="Failed" value={c.failed} tone="text-rose-600" />}
      </div>
      {isWa && (
        <div className="mt-2 grid grid-cols-3 gap-1 text-center">
          <Stat label="Replies" value={c.replied} tone="text-violet-600" />
          <Stat label="Queued" value={c.queued} tone="text-sky-600" />
          <Stat label="Failed" value={c.failed} tone="text-rose-600" />
        </div>
      )}

      {c.failed > 0 && (
        <button onClick={onFailures} className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-rose-500 hover:underline" data-testid={`campaign-failures-${c.id}`}>
          <WarningCircle size={13} /> View {c.failed} failure{c.failed > 1 ? "s" : ""} & reasons
        </button>
      )}

      <p className="mt-2 text-xs text-slate-400">{c.created_by} · {fmtDate(c.created_at)}</p>

      <div className="mt-3 flex items-center justify-between border-t border-slate-50 pt-3">
        <div className="flex items-center gap-2">
          <button onClick={onDelete} className="text-slate-400 hover:text-rose-500" title="Delete" data-testid={`campaign-delete-${c.id}`}><Trash size={16} /></button>
          {!running && <button onClick={onEdit} className="text-slate-400 hover:text-[#357ABD]" title="Edit" data-testid={`campaign-edit-${c.id}`}><PencilSimple size={16} /></button>}
        </div>
        <div className="flex items-center gap-2">
          {running ? (
            <button onClick={onPause} className="hivf-btn-secondary !py-1.5 text-xs" data-testid={`campaign-pause-${c.id}`}><Pause size={14} /> Pause</button>
          ) : c.status === "paused" ? (
            <button onClick={onSend} className="hivf-btn-primary !py-1.5 text-xs" data-testid={`campaign-resume-${c.id}`}><ArrowClockwise size={14} /> Resume</button>
          ) : c.status === "completed" ? (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600"><CheckCircle size={15} weight="fill" /> Completed</span>
          ) : (
            <button onClick={onSend} disabled={!c.template_id} className="hivf-btn-primary !py-1.5 text-xs disabled:opacity-40" data-testid={`campaign-send-${c.id}`}><PaperPlaneTilt size={14} /> Send</button>
          )}
        </div>
      </div>
    </div>
  );
}

function TemplatePreview({ channel, template }) {
  if (!template) return null;
  const sample = (s) => (s || "").replace(/\{\{1\}\}/g, "Priya Sharma").replace(/\{\{\d\}\}/g, "…");
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3" data-testid="template-preview">
      <p className="mb-1.5 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        {channel === "whatsapp" ? <WhatsappLogo size={13} className="text-emerald-500" /> : <ChatCircleDots size={13} className="text-[#357ABD]" />} Preview
      </p>
      {channel === "email" && template.subject && (
        <p className="mb-2 text-xs"><span className="font-semibold text-slate-500">Subject:</span> {sample(template.subject)}</p>
      )}
      {channel === "whatsapp" ? (
        <div className="rounded-lg bg-[#dcf8c6] px-3 py-2 text-sm text-slate-800 whitespace-pre-wrap" data-testid="template-preview-body">{sample(template.body) || "—"}</div>
      ) : (
        <div className="max-h-40 overflow-auto rounded-lg border border-slate-200 bg-white p-2 text-sm text-slate-700" data-testid="template-preview-body" dangerouslySetInnerHTML={{ __html: sample(template.body) || "—" }} />
      )}
    </div>
  );
}

function CampaignModal({ editing, onClose, onSaved }) {
  const { catalogs } = useCatalogs();
  const init = editing ? {
    name: editing.name, channel: editing.channel, template_id: editing.template_id ? String(editing.template_id) : "",
    lead_stage: editing.audience?.lead_stage || "", source_lead: editing.audience?.source_lead || "",
    tags: editing.audience?.tags || "", city: editing.audience?.city || "", state_name: editing.audience?.state_name || "",
  } : { name: "", channel: "whatsapp", template_id: "", lead_stage: "", source_lead: "", tags: "", city: "", state_name: "" };
  const [form, setForm] = useState(init);
  const [templates, setTemplates] = useState([]);
  const [count, setCount] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    API.get(`/templates/${form.channel}`).then(({ data }) => setTemplates(data));
    if (!editing) setForm((f) => ({ ...f, template_id: "" }));
  }, [form.channel]);

  const selectedTpl = templates.find((t) => String(t.id) === String(form.template_id));

  const audience = () => {
    const a = { active: "true" };
    ["lead_stage", "source_lead", "tags", "city", "state_name"].forEach((k) => { if (form[k]) a[k] = form[k]; });
    return a;
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Campaign name required"); return; }
    setSaving(true);
    try {
      const payload = { name: form.name.trim(), channel: form.channel, template_id: form.template_id ? Number(form.template_id) : null, audience: audience() };
      if (editing) {
        await API.patch(`/marketing/campaigns/${editing.id}`, { name: payload.name, template_id: payload.template_id, audience: payload.audience });
        toast.success("Campaign updated");
      } else {
        const { data } = await API.post("/marketing/campaigns", payload);
        const { data: cnt } = await API.post(`/marketing/campaigns/${data.id}/audience-count`);
        toast.success(`Campaign created — ${cnt.count} recipients matched`);
      }
      onSaved();
    } catch (e) { toast.error(apiErr(e)); } finally { setSaving(false); }
  };

  const preview = async () => {
    setSaving(true);
    try {
      const { data } = await API.post("/marketing/campaigns", { name: form.name.trim() || "preview", channel: form.channel, template_id: null, audience: audience() });
      const { data: cnt } = await API.post(`/marketing/campaigns/${data.id}/audience-count`);
      setCount(cnt.count);
      await API.delete(`/marketing/campaigns/${data.id}`);
    } catch (e) { toast.error(apiErr(e)); } finally { setSaving(false); }
  };

  const stages = catalogs?.lead_stage || [];
  const sources = catalogs?.source_lead || [];
  const tags = catalogs?.tag || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="max-h-[90vh] w-full max-w-lg overflow-auto rounded-2xl bg-white p-6 shadow-xl" data-testid="campaign-modal">
        <h3 className="flex items-center gap-2 font-display text-lg font-extrabold text-slate-900"><Megaphone size={20} className="text-[#8B5CF6]" /> {editing ? "Edit Campaign" : "New Campaign"}</h3>
        <div className="mt-4 space-y-3">
          <input data-testid="campaign-name-input" className="hivf-input" placeholder="Campaign name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          <div className="flex gap-2">
            <button onClick={() => setForm((f) => ({ ...f, channel: "whatsapp" }))} className={`flex-1 rounded-lg border px-3 py-2 text-sm font-bold ${form.channel === "whatsapp" ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200 text-slate-500"}`} data-testid="campaign-channel-whatsapp"><WhatsappLogo size={15} className="mr-1 inline" /> WhatsApp</button>
            <button onClick={() => setForm((f) => ({ ...f, channel: "email" }))} className={`flex-1 rounded-lg border px-3 py-2 text-sm font-bold ${form.channel === "email" ? "border-[#4A90E2]/40 bg-[#4A90E2]/10 text-[#357ABD]" : "border-slate-200 text-slate-500"}`} data-testid="campaign-channel-email"><EnvelopeSimple size={15} className="mr-1 inline" /> Email</button>
          </div>
          <select data-testid="campaign-template-select" className="hivf-select w-full" value={form.template_id} onChange={(e) => setForm((f) => ({ ...f, template_id: e.target.value }))}>
            <option value="">— Select template —</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>

          <TemplatePreview channel={form.channel} template={selectedTpl} />

          <p className="pt-1 text-xs font-bold uppercase tracking-wider text-slate-400">Audience filters</p>
          <div className="grid grid-cols-2 gap-2">
            <select className="hivf-select" value={form.lead_stage} onChange={(e) => setForm((f) => ({ ...f, lead_stage: e.target.value }))} data-testid="campaign-stage-filter">
              <option value="">Any lead stage</option>{stages.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
            <select className="hivf-select" value={form.source_lead} onChange={(e) => setForm((f) => ({ ...f, source_lead: e.target.value }))} data-testid="campaign-source-filter">
              <option value="">Any source</option>{sources.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
            <select className="hivf-select" value={form.tags} onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))} data-testid="campaign-tag-filter">
              <option value="">Any tag</option>{tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <input className="hivf-input" placeholder="City" value={form.city} onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))} />
          </div>
          <button onClick={preview} disabled={saving} className="hivf-btn-secondary !py-1.5 text-xs" data-testid="campaign-preview-button"><Users size={14} /> Preview audience size</button>
          {count !== null && <p className="text-sm font-bold text-[#357ABD]" data-testid="campaign-audience-count">{count} recipients match this audience</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button onClick={save} disabled={saving} className="hivf-btn-primary" data-testid="campaign-create-button">{editing ? "Save Changes" : "Create Campaign"}</button>
        </div>
      </div>
    </div>
  );
}

function FailuresModal({ campaign, onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    API.get(`/marketing/campaigns/${campaign.id}/failures`).then(({ data }) => setRows(data.failures || []));
  }, [campaign.id]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="max-h-[80vh] w-full max-w-lg overflow-auto rounded-2xl bg-white p-6 shadow-xl" data-testid="campaign-failures-modal">
        <h3 className="flex items-center gap-2 font-display text-lg font-extrabold text-slate-900"><WarningCircle size={20} className="text-rose-500" /> Failed messages — {campaign.name}</h3>
        {!rows ? <Spinner /> : rows.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">No failure details recorded.</p>
        ) : (
          <table className="mt-4 w-full text-left text-xs">
            <thead><tr className="text-slate-400"><th className="pb-2">To</th><th className="pb-2">Reason</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-slate-50" data-testid={`failure-row-${i}`}>
                  <td className="py-1.5 pr-2 font-mono text-slate-600">{r.to || `Lead ${r.lead_id}`}</td>
                  <td className="py-1.5 text-rose-600">{r.error}{r.code ? ` (${r.code})` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="mt-5 flex justify-end"><button onClick={onClose} className="hivf-btn-secondary">Close</button></div>
      </div>
    </div>
  );
}
