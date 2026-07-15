import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, NotePencil, Trash, WhatsappLogo, EnvelopeSimple, ArrowRight } from "@phosphor-icons/react";
import { API, apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Spinner, EmptyState } from "../components/Bits";

export default function Templates() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [channel, setChannel] = useState("whatsapp");
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null); // null | {} | template

  const load = async (ch = channel) => {
    setItems(null);
    const { data } = await API.get(`/templates/${ch}`);
    setItems(data);
  };

  useEffect(() => { load(channel); /* eslint-disable-next-line */ }, [channel]);

  const canEdit = user.role !== "caller";

  const newTemplate = async () => {
    if (channel === "email") { setEditing({}); return; }
    try {
      const { data } = await API.post(`/templates/whatsapp`, { name: "New WhatsApp Template", body: "", status: "draft" });
      navigate(`/templates/whatsapp/${data.id}`);
    } catch (e) { toast.error(apiErr(e)); }
  };

  const save = async (form) => {
    try {
      if (form.id) await API.patch(`/templates/${channel}/${form.id}`, form);
      else await API.post(`/templates/${channel}`, form);
      toast.success("Template saved");
      setEditing(null);
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this template?")) return;
    await API.delete(`/templates/${channel}/${id}`);
    load();
  };

  return (
    <div className="p-6" data-testid="templates-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-slate-900">Templates</h1>
          <p className="text-sm text-slate-500">WhatsApp & Email templates</p>
        </div>
        {canEdit && (
          <button data-testid="new-template-button" onClick={newTemplate} className="hivf-btn-primary"><Plus size={15} /> New Template</button>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <button data-testid="templates-tab-whatsapp" onClick={() => setChannel("whatsapp")}
          className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-bold ${channel === "whatsapp" ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-500"}`}>
          <WhatsappLogo size={16} /> WhatsApp
        </button>
        <button data-testid="templates-tab-email" onClick={() => setChannel("email")}
          className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-bold ${channel === "email" ? "border-[#4A90E2]/40 bg-[#4A90E2]/10 text-[#357ABD]" : "border-slate-200 bg-white text-slate-500"}`}>
          <EnvelopeSimple size={16} /> Email
        </button>
      </div>

      {!items ? <Spinner /> : items.length === 0 ? (
        <EmptyState title="No templates" />
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="templates-grid">
          {items.map((t) => (
            <div key={t.id} data-testid={`template-card-${t.id}`}
              onClick={() => channel === "whatsapp" && navigate(`/templates/whatsapp/${t.id}`)}
              className={`hivf-card flex flex-col p-4 transition-all hover:-translate-y-[2px] hover:shadow-md ${channel === "whatsapp" ? "cursor-pointer" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-bold text-slate-800">{t.name}</p>
                <div className="flex shrink-0 gap-1">
                  {t.status && <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold capitalize ${t.status === "approved" ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>{t.status}</span>}
                  {t.template_type && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500">{t.template_type}</span>}
                </div>
              </div>
              {t.subject && <p className="mt-1 text-xs font-semibold text-slate-600">{t.subject}</p>}
              <div className="chatter-body mt-2 line-clamp-4 flex-1 text-xs text-slate-500" dangerouslySetInnerHTML={{ __html: (t.body || "").slice(0, 400) }} />
              <div className="mt-3 flex items-center justify-end gap-2 border-t border-slate-50 pt-2">
                {channel === "whatsapp" ? (
                  <span className="inline-flex items-center gap-1 text-xs font-bold text-[#357ABD]" data-testid={`open-template-${t.id}`}>Open <ArrowRight size={13} /></span>
                ) : canEdit && (
                  <>
                    <button data-testid={`edit-template-${t.id}`} onClick={(e) => { e.stopPropagation(); setEditing(t); }} className="text-slate-400 hover:text-[#4A90E2]"><NotePencil size={16} /></button>
                    {user.role === "admin" && <button onClick={(e) => { e.stopPropagation(); remove(t.id); }} className="text-slate-400 hover:text-rose-500"><Trash size={16} /></button>}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {editing !== null && (
        <TemplateModal channel={channel} template={editing} onClose={() => setEditing(null)} onSave={save} />
      )}
    </div>
  );
}

function TemplateModal({ channel, template, onClose, onSave }) {
  const [form, setForm] = useState({
    id: template.id, name: template.name || "", subject: template.subject || "",
    body: template.body || "", template_type: template.template_type || "utility", status: template.status || "draft",
    wa_template_name: template.wa_template_name || "", lang: template.lang || "en",
  });
  const SAMPLE = { "{{1}}": "Riya Sharma", "{{2}}": "HomeIVF", "{{3}}": "12 Jun" };
  const rendered = (form.body || "").replace(/\{\{(\d+)\}\}/g, (m) => SAMPLE[m] || m);
  const [previewMode, setPreviewMode] = useState("rendered");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSave(form); }} onClick={(e) => e.stopPropagation()}
        className="grid w-full max-w-3xl grid-cols-1 gap-5 rounded-2xl bg-white p-6 shadow-xl md:grid-cols-2" data-testid="template-modal">
        <div>
          <h3 className="font-display text-lg font-extrabold text-slate-900">{form.id ? "Edit" : "New"} {channel} template</h3>
          <div className="mt-4 space-y-3">
            <input data-testid="template-name-input" required className="hivf-input" placeholder="Template name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            {channel === "email" && (
              <input className="hivf-input" placeholder="Subject" value={form.subject} onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))} data-testid="template-subject-input" />
            )}
            {channel === "whatsapp" && (
              <>
                <div className="flex gap-2">
                  <select className="hivf-select flex-1" value={form.template_type} onChange={(e) => setForm((f) => ({ ...f, template_type: e.target.value }))}>
                    <option value="utility">Utility</option><option value="marketing">Marketing</option>
                  </select>
                  <select className="hivf-select flex-1" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                    <option value="draft">Draft</option><option value="pending">Pending</option><option value="approved">Approved</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <input className="hivf-input flex-1" placeholder="Meta approved template name (optional)" value={form.wa_template_name} onChange={(e) => setForm((f) => ({ ...f, wa_template_name: e.target.value }))} data-testid="template-wa-name-input" />
                  <input className="hivf-input !w-24" placeholder="lang (en)" value={form.lang} onChange={(e) => setForm((f) => ({ ...f, lang: e.target.value }))} />
                </div>
              </>
            )}
            {channel === "email" && (
              <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">Email HTML body</label>
            )}
            <textarea data-testid="template-body-input" required rows={channel === "email" ? 12 : 8} className="hivf-input font-mono text-xs"
              placeholder={channel === "email"
                ? "Paste your HTML email here, e.g. <h2>Hi {{1}}</h2><p>Your appointment is on {{3}}.</p><a href='...'>Book now</a>"
                : "Body — use {{1}}, {{2}} for variables (e.g. Hi {{1}}, your appointment is on {{3}})"}
              value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} />
            <p className="text-[11px] text-slate-400">
              {channel === "email" && <><b>Full HTML supported</b> — tags, inline styles, links & tables render in the email. <br /></>}
              Variables: <b>{"{{1}}"}</b> = lead name, <b>{"{{2}}"}</b>, <b>{"{{3}}"}</b> = extra params. Preview shows sample values.
            </p>
          </div>
        </div>
        <div className="flex flex-col">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Live Preview</p>
            {channel === "email" && (
              <div className="flex gap-1 rounded-lg bg-slate-100 p-0.5" data-testid="email-preview-toggle">
                <button type="button" onClick={() => setPreviewMode("rendered")} data-testid="preview-rendered-btn"
                  className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${previewMode === "rendered" ? "bg-white text-[#357ABD] shadow-sm" : "text-slate-400"}`}>Rendered</button>
                <button type="button" onClick={() => setPreviewMode("source")} data-testid="preview-source-btn"
                  className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${previewMode === "source" ? "bg-white text-[#357ABD] shadow-sm" : "text-slate-400"}`}>HTML source</button>
              </div>
            )}
          </div>
          <div className="mt-2 flex-1 overflow-auto rounded-xl border border-slate-100 bg-slate-50 p-4" data-testid="template-preview">
            {channel === "whatsapp" ? (
              <div className="rounded-xl rounded-tl-sm bg-[#dcf8c6] p-3 text-sm text-slate-800 shadow-sm whitespace-pre-wrap">{rendered || "Your message preview appears here…"}</div>
            ) : (
              <div className="rounded-xl bg-white p-3 text-sm shadow-sm">
                <p className="border-b border-slate-100 pb-2 font-bold text-slate-800">{form.subject || "(no subject)"}</p>
                {previewMode === "source" ? (
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-slate-500">{rendered || "Your HTML appears here…"}</pre>
                ) : rendered ? (
                  <div className="chatter-body mt-2 text-slate-700" data-testid="email-preview-rendered" dangerouslySetInnerHTML={{ __html: rendered }} />
                ) : (
                  <div className="mt-2 text-slate-400">Your email design preview appears here…</div>
                )}
              </div>
            )}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
            <button data-testid="template-save-button" type="submit" className="hivf-btn-primary">Save</button>
          </div>
        </div>
      </form>
    </div>
  );
}
