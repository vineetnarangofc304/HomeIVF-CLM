import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash, PaperPlaneTilt, WhatsappLogo, EnvelopeSimple, Users, Megaphone } from "@phosphor-icons/react";
import { API, apiErr, fmtDate } from "../lib/api";
import { useCatalogs } from "../context/AuthContext";
import { Spinner, EmptyState } from "../components/Bits";

const STATUS_BADGE = {
  draft: "bg-slate-100 text-slate-500", sending: "bg-amber-50 text-amber-600",
  sent: "bg-emerald-50 text-emerald-600", partial: "bg-indigo-50 text-indigo-600",
  queued: "bg-sky-50 text-sky-600",
};

export default function Marketing() {
  const [campaigns, setCampaigns] = useState(null);
  const [show, setShow] = useState(false);

  const load = () => API.get("/marketing/campaigns").then(({ data }) => setCampaigns(data));
  useEffect(() => { load(); }, []);

  const send = async (c) => {
    if (!c.template_id) { toast.error("Attach a template before sending"); return; }
    if (!window.confirm(`Send "${c.name}" to the matched audience now?`)) return;
    try {
      const { data } = await API.post(`/marketing/campaigns/${c.id}/send`);
      toast.success(`Done — ${data.sent} sent, ${data.queued} queued, ${data.failed} failed${data.live ? " (live)" : " (queued: API not connected)"}`);
      load();
    } catch (e) { toast.error(apiErr(e)); }
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
        <button data-testid="new-campaign-button" onClick={() => setShow(true)} className="hivf-btn-primary"><Plus size={15} /> New Campaign</button>
      </div>

      {!campaigns ? <Spinner /> : campaigns.length === 0 ? (
        <div className="mt-6"><EmptyState title="No campaigns yet" subtitle="Create your first bulk WhatsApp or Email campaign" /></div>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="campaigns-grid">
          {campaigns.map((c) => (
            <div key={c.id} className="hivf-card flex flex-col p-4" data-testid={`campaign-card-${c.id}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  {c.channel === "whatsapp" ? <WhatsappLogo size={18} className="text-emerald-500" /> : <EnvelopeSimple size={18} className="text-[#357ABD]" />}
                  <p className="text-sm font-bold text-slate-800">{c.name}</p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATUS_BADGE[c.status] || "bg-slate-100 text-slate-500"}`}>{c.status}</span>
              </div>
              <div className="mt-3 grid grid-cols-4 gap-1 text-center">
                {[["Total", c.total], ["Sent", c.sent], ["Queued", c.queued], ["Failed", c.failed]].map(([l, v]) => (
                  <div key={l}><p className="font-display text-base font-extrabold text-slate-800">{v}</p><p className="text-[10px] uppercase tracking-wider text-slate-400">{l}</p></div>
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-400">{c.created_by} · {fmtDate(c.created_at)}</p>
              <div className="mt-3 flex justify-end gap-2 border-t border-slate-50 pt-3">
                <button onClick={() => remove(c.id)} className="text-slate-400 hover:text-rose-500" data-testid={`campaign-delete-${c.id}`}><Trash size={16} /></button>
                <button onClick={() => send(c)} disabled={c.status === "sending"} className="hivf-btn-primary !py-1.5 text-xs" data-testid={`campaign-send-${c.id}`}>
                  <PaperPlaneTilt size={14} /> Send
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {show && <CampaignModal onClose={() => setShow(false)} onSaved={() => { setShow(false); load(); }} />}
    </div>
  );
}

function CampaignModal({ onClose, onSaved }) {
  const { catalogs } = useCatalogs();
  const [form, setForm] = useState({ name: "", channel: "whatsapp", template_id: "", lead_stage: "", source_lead: "", tags: "", city: "", state_name: "" });
  const [templates, setTemplates] = useState([]);
  const [count, setCount] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    API.get(`/templates/${form.channel}`).then(({ data }) => setTemplates(data));
    setForm((f) => ({ ...f, template_id: "" }));
  }, [form.channel]);

  const audience = () => {
    const a = { active: "true" };
    ["lead_stage", "source_lead", "tags", "city", "state_name"].forEach((k) => { if (form[k]) a[k] = form[k]; });
    return a;
  };

  const create = async () => {
    if (!form.name.trim()) { toast.error("Campaign name required"); return; }
    setSaving(true);
    try {
      const { data } = await API.post("/marketing/campaigns", {
        name: form.name.trim(), channel: form.channel,
        template_id: form.template_id ? Number(form.template_id) : null, audience: audience(),
      });
      // preview count for confirmation
      const { data: cnt } = await API.post(`/marketing/campaigns/${data.id}/audience-count`);
      toast.success(`Campaign created — ${cnt.count} recipients matched`);
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
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl" data-testid="campaign-modal">
        <h3 className="flex items-center gap-2 font-display text-lg font-extrabold text-slate-900"><Megaphone size={20} className="text-[#8B5CF6]" /> New Campaign</h3>
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
          <button onClick={create} disabled={saving} className="hivf-btn-primary" data-testid="campaign-create-button">Create Campaign</button>
        </div>
      </div>
    </div>
  );
}
