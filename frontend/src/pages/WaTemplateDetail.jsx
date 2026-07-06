import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash, ChatText, PaperPlaneTilt } from "@phosphor-icons/react";
import { API, apiErr } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "../components/Bits";

const APPROVAL_STEPS = ["draft", "pending", "approved"];
const BUTTON_TYPES = ["Call Number", "Visit Website", "Quick Reply", "Set Automation"];
const VAR_TYPES = ["Field of Model", "User Name", "User Phone", "Free Text"];

export default function WaTemplateDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user.role !== "caller";
  const [tpl, setTpl] = useState(null);
  const [tab, setTab] = useState("body");
  const [summary, setSummary] = useState(null);

  const load = async () => {
    try {
      const { data } = await API.get(`/templates/whatsapp/${id}`);
      setTpl({
        ...data,
        user_access: data.user_access || "all",
        buttons: data.buttons || [],
        variables: data.variables || [],
        status: data.status || "draft",
      });
      const { data: s } = await API.get(`/wa/template/${id}/summary`);
      setSummary(s);
    } catch (e) { toast.error(apiErr(e)); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const set = (k, v) => setTpl((t) => ({ ...t, [k]: v }));

  const save = async () => {
    try {
      await API.patch(`/templates/whatsapp/${id}`, {
        name: tpl.name, body: tpl.body, applies_to: tpl.applies_to, phone_field: tpl.phone_field,
        lang: tpl.lang, header_type: tpl.header_type, category: tpl.category, footer: tpl.footer,
        user_access: tpl.user_access, buttons: tpl.buttons, variables: tpl.variables, status: tpl.status,
        wa_template_name: tpl.wa_template_name,
      });
      toast.success("Template saved");
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  if (!tpl) return <Spinner />;
  const SAMPLE = { "{{1}}": "Riya Sharma", "{{2}}": "HomeIVF", "{{3}}": "12 Jun" };
  const rendered = (tpl.body || "").replace(/\{\{(\d+)\}\}/g, (m) => SAMPLE[m] || m);

  return (
    <div className="p-6" data-testid="wa-template-detail">
      <button onClick={() => navigate("/templates")} className="mb-3 inline-flex items-center gap-1 text-sm font-bold text-slate-400 hover:text-slate-600"><ArrowLeft size={15} /> Back to Templates</button>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-slate-900" data-testid="wa-template-name">{tpl.name}</h1>
          {/* 3-step approval flow */}
          <div className="mt-3 flex items-center gap-1" data-testid="approval-flow">
            {APPROVAL_STEPS.map((step, i) => {
              const active = APPROVAL_STEPS.indexOf(tpl.status) >= i;
              return (
                <React.Fragment key={step}>
                  <button disabled={!canEdit} onClick={() => set("status", step)} data-testid={`approval-${step}`}
                    className={`rounded-full px-3 py-1 text-[11px] font-bold capitalize transition-colors ${active ? "bg-[#25D366] text-white" : "bg-slate-100 text-slate-400"} ${canEdit ? "cursor-pointer" : ""}`}>{step}</button>
                  {i < APPROVAL_STEPS.length - 1 && <span className={`h-0.5 w-6 ${APPROVAL_STEPS.indexOf(tpl.status) > i ? "bg-[#25D366]" : "bg-slate-200"}`} />}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* Approved summary box (Ad Messages) */}
        {tpl.status === "approved" && summary && (
          <button data-testid="ad-messages-box" onClick={() => navigate(`/templates/whatsapp/${id}/messages`)}
            className="rounded-2xl border border-[#25D366]/30 bg-[#25D366]/5 p-4 text-left transition-all hover:-translate-y-[2px] hover:shadow-md">
            <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-600">Ad Messages</p>
            <p className="font-display text-3xl font-extrabold text-slate-800" data-testid="ad-messages-count">{summary.total}</p>
            <p className="text-[11px] text-slate-500">Total triggered messages · click to view log →</p>
          </button>
        )}
      </div>

      {/* Template info */}
      <div className="mt-5 grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-white p-4 md:grid-cols-3" data-testid="template-info">
        <Field label="Template Name"><input className="hivf-input" disabled={!canEdit} value={tpl.name || ""} onChange={(e) => set("name", e.target.value)} data-testid="info-name" /></Field>
        <Field label="Applies To"><input className="hivf-input" disabled={!canEdit} placeholder="Lead" value={tpl.applies_to || ""} onChange={(e) => set("applies_to", e.target.value)} /></Field>
        <Field label="Phone Field"><input className="hivf-input" disabled={!canEdit} placeholder="Phone" value={tpl.phone_field || ""} onChange={(e) => set("phone_field", e.target.value)} /></Field>
        <Field label="Language"><input className="hivf-input" disabled={!canEdit} placeholder="English" value={tpl.lang || ""} onChange={(e) => set("lang", e.target.value)} /></Field>
        <Field label="Header Type"><input className="hivf-input" disabled={!canEdit} placeholder="None / Text / Media" value={tpl.header_type || ""} onChange={(e) => set("header_type", e.target.value)} /></Field>
        <Field label="Category">
          <select className="hivf-select" disabled={!canEdit} value={tpl.category || ""} onChange={(e) => set("category", e.target.value)}>
            <option value="">Select…</option><option>Marketing</option><option>Utility</option><option>Authentication</option>
          </select>
        </Field>
        <Field label="Footer Message"><input className="hivf-input" disabled={!canEdit} value={tpl.footer || ""} onChange={(e) => set("footer", e.target.value)} /></Field>
        <Field label="Meta Approved Name"><input className="hivf-input" disabled={!canEdit} placeholder="contact_attempt_not_picked" value={tpl.wa_template_name || ""} onChange={(e) => set("wa_template_name", e.target.value)} /></Field>
        <Field label="Users">
          <select className="hivf-select" disabled={!canEdit} value={typeof tpl.user_access === "string" ? tpl.user_access : "all"} onChange={(e) => set("user_access", e.target.value)}>
            <option value="all">Accessible to all users</option><option value="specific">Specific users</option>
          </select>
        </Field>
      </div>

      {/* Tabs */}
      <div className="mt-5 flex gap-2" data-testid="template-tabs">
        {[["body", "Body", ChatText], ["button", "Button", PaperPlaneTilt], ["variables", "Variables", Plus]].map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`tab-${k}`}
            className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-bold ${tab === k ? "border-[#25D366]/40 bg-[#25D366]/10 text-emerald-700" : "border-slate-200 bg-white text-slate-500"}`}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {tab === "body" && (
            <textarea rows={10} disabled={!canEdit} className="hivf-input w-full font-mono text-xs" data-testid="body-input"
              placeholder="Body — use {{1}}, {{2}} for variables" value={tpl.body || ""} onChange={(e) => set("body", e.target.value)} />
          )}
          {tab === "button" && <ButtonsTab tpl={tpl} set={set} canEdit={canEdit} />}
          {tab === "variables" && <VariablesTab tpl={tpl} set={set} canEdit={canEdit} />}
        </div>
        {/* Live preview */}
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Live Preview</p>
          <div className="mt-2 rounded-xl border border-slate-100 bg-slate-50 p-4">
            <div className="rounded-xl rounded-tl-sm bg-[#dcf8c6] p-3 text-sm text-slate-800 shadow-sm whitespace-pre-wrap" data-testid="wa-preview">{rendered || "Your message preview appears here…"}</div>
            {tpl.footer && <p className="mt-1 px-1 text-[11px] text-slate-400">{tpl.footer}</p>}
            {(tpl.buttons || []).length > 0 && (
              <div className="mt-2 space-y-1">
                {tpl.buttons.map((b, i) => <div key={i} className="rounded-lg bg-white py-1.5 text-center text-xs font-bold text-[#357ABD] shadow-sm">{b.text || b.type}</div>)}
              </div>
            )}
          </div>
        </div>
      </div>

      {canEdit && (
        <div className="mt-6 flex justify-end">
          <button onClick={save} className="hivf-btn-primary" data-testid="template-submit-button"><PaperPlaneTilt size={15} /> Submit</button>
        </div>
      )}
    </div>
  );
}

const Field = ({ label, children }) => (
  <div>
    <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</label>
    <div className="mt-1">{children}</div>
  </div>
);

function ButtonsTab({ tpl, set, canEdit }) {
  const buttons = tpl.buttons || [];
  const upd = (i, k, v) => set("buttons", buttons.map((b, idx) => idx === i ? { ...b, [k]: v } : b));
  return (
    <div className="space-y-3" data-testid="buttons-tab">
      {buttons.map((b, i) => (
        <div key={i} className="rounded-xl border border-slate-100 p-3">
          <div className="grid grid-cols-2 gap-2">
            <select className="hivf-select" disabled={!canEdit} value={b.type || ""} onChange={(e) => upd(i, "type", e.target.value)}>
              <option value="">Type…</option>{BUTTON_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input className="hivf-input" disabled={!canEdit} placeholder="Button Text" value={b.text || ""} onChange={(e) => upd(i, "text", e.target.value)} />
            <input className="hivf-input" disabled={!canEdit} placeholder="Call Number" value={b.call_number || ""} onChange={(e) => upd(i, "call_number", e.target.value)} />
            <input className="hivf-input" disabled={!canEdit} placeholder="Website URL" value={b.url || ""} onChange={(e) => upd(i, "url", e.target.value)} />
            <input className="hivf-input" disabled={!canEdit} placeholder="URL Type (static/dynamic)" value={b.url_type || ""} onChange={(e) => upd(i, "url_type", e.target.value)} />
          </div>
          {canEdit && <button onClick={() => set("buttons", buttons.filter((_, idx) => idx !== i))} className="mt-2 text-xs font-bold text-rose-500"><Trash size={13} className="inline" /> Remove</button>}
        </div>
      ))}
      {canEdit && <button onClick={() => set("buttons", [...buttons, { type: "Quick Reply", text: "" }])} className="hivf-btn-secondary !py-1.5 text-xs" data-testid="add-button"><Plus size={13} /> Add button</button>}
    </div>
  );
}

function VariablesTab({ tpl, set, canEdit }) {
  const vars = tpl.variables || [];
  const upd = (i, k, v) => set("variables", vars.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  return (
    <div className="space-y-3" data-testid="variables-tab">
      {vars.map((v, i) => (
        <div key={i} className="rounded-xl border border-slate-100 p-3">
          <div className="grid grid-cols-2 gap-2">
            <input className="hivf-input" disabled={!canEdit} placeholder="Name e.g. Body - {{1}}" value={v.name || ""} onChange={(e) => upd(i, "name", e.target.value)} />
            <input className="hivf-input" disabled={!canEdit} placeholder="Sample Value" value={v.sample || ""} onChange={(e) => upd(i, "sample", e.target.value)} />
            <select className="hivf-select" disabled={!canEdit} value={v.type || ""} onChange={(e) => upd(i, "type", e.target.value)}>
              <option value="">Type…</option>{VAR_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input className="hivf-input" disabled={!canEdit} placeholder="Field (lead field key)" value={v.field || ""} onChange={(e) => upd(i, "field", e.target.value)} />
          </div>
          {canEdit && <button onClick={() => set("variables", vars.filter((_, idx) => idx !== i))} className="mt-2 text-xs font-bold text-rose-500"><Trash size={13} className="inline" /> Remove</button>}
        </div>
      ))}
      {canEdit && <button onClick={() => set("variables", [...vars, { name: `Body - {{${vars.length + 1}}}`, sample: "", type: "Free Text" }])} className="hivf-btn-secondary !py-1.5 text-xs" data-testid="add-variable"><Plus size={13} /> Add variable</button>}
    </div>
  );
}
