import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash, ArrowsClockwise, Copy } from "@phosphor-icons/react";
import { API, apiErr } from "../lib/api";
import { useAuth, useCatalogs, useCatalogMaps } from "../context/AuthContext";
import { Spinner, TagChip } from "../components/Bits";

const TABS = ["Users", "Tags", "Dropdowns", "Webhooks", "Automations", "Assignment", "Migration"];

export default function Admin() {
  const { user } = useAuth();
  const [tab, setTab] = useState("Users");
  return (
    <div className="p-6" data-testid="admin-page">
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Admin</h1>
      <p className="text-sm text-slate-500">Manage everything that powers your CRM</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t} data-testid={`admin-tab-${t.toLowerCase()}`} onClick={() => setTab(t)}
            className={`rounded-full border px-4 py-2 text-sm font-bold transition-colors ${tab === t ? "border-[#4A90E2] bg-[#4A90E2]/10 text-[#357ABD]" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="mt-5">
        {tab === "Users" && <UsersTab isAdmin={user.role === "admin"} />}
        {tab === "Tags" && <CatalogTab ctype="tag" title="Disposition Tags" withColor />}
        {tab === "Dropdowns" && <DropdownsTab />}
        {tab === "Webhooks" && <WebhooksTab />}
        {tab === "Automations" && <AutomationsTab />}
        {tab === "Assignment" && <AssignmentTab />}
        {tab === "Migration" && <MigrationTab />}
      </div>
    </div>
  );
}

function UsersTab({ isAdmin }) {
  const [users, setUsers] = useState(null);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "caller" });
  const { refreshCatalogs } = useCatalogs();

  const load = () => API.get("/users").then(({ data }) => setUsers(data));
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    try {
      await API.post("/users", form);
      toast.success("User created");
      setShow(false); setForm({ name: "", email: "", password: "", role: "caller" });
      load(); refreshCatalogs();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const patch = async (id, updates) => {
    try {
      await API.patch(`/users/${id}`, updates);
      toast.success("Updated");
      load(); refreshCatalogs();
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!users) return <Spinner />;
  return (
    <div className="hivf-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 p-4">
        <p className="text-sm font-bold text-slate-700">{users.length} users</p>
        {isAdmin && <button data-testid="add-user-button" onClick={() => setShow(true)} className="hivf-btn-primary !py-1.5 text-xs"><Plus size={14} /> Add user</button>}
      </div>
      <table className="w-full text-sm" data-testid="users-table">
        <thead className="bg-slate-50">
          <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
            <th className="px-4 py-2">Name</th><th className="px-2 py-2">Email</th><th className="px-2 py-2">Role</th><th className="px-2 py-2">Status</th>{isAdmin && <th className="px-2 py-2">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-slate-50">
              <td className="px-4 py-2 font-semibold text-slate-700">{u.name}</td>
              <td className="px-2 py-2 text-slate-500">{u.email}</td>
              <td className="px-2 py-2">
                {isAdmin ? (
                  <select className="hivf-select !py-1" value={u.role} onChange={(e) => patch(u.id, { role: e.target.value })} data-testid={`role-select-${u.id}`}>
                    <option value="admin">admin</option><option value="manager">manager</option><option value="caller">caller</option>
                  </select>
                ) : <span className="capitalize">{u.role}</span>}
              </td>
              <td className="px-2 py-2">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${u.active ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>{u.active ? "active" : "inactive"}</span>
              </td>
              {isAdmin && (
                <td className="px-2 py-2">
                  <button className="mr-2 text-xs font-bold text-[#357ABD]" onClick={() => { const p = window.prompt(`New password for ${u.name}:`); if (p) patch(u.id, { password: p }); }}>Reset pwd</button>
                  <button className="text-xs font-bold text-slate-400" onClick={() => patch(u.id, { active: !u.active })}>{u.active ? "Deactivate" : "Activate"}</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setShow(false)}>
          <form onSubmit={create} onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl" data-testid="add-user-modal">
            <h3 className="font-display text-lg font-extrabold">New User</h3>
            <div className="mt-4 space-y-3">
              <input data-testid="user-name-input" required className="hivf-input" placeholder="Full name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
              <input data-testid="user-email-input" required type="email" className="hivf-input" placeholder="Email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
              <input data-testid="user-password-input" required className="hivf-input" placeholder="Password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
              <select data-testid="user-role-select" className="hivf-select w-full" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                <option value="caller">Caller</option><option value="manager">Manager</option><option value="admin">Admin</option>
              </select>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setShow(false)} className="hivf-btn-secondary">Cancel</button>
              <button data-testid="user-create-submit" type="submit" className="hivf-btn-primary">Create</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function CatalogTab({ ctype, title, withColor }) {
  const { catalogs, refreshCatalogs } = useCatalogs();
  const [name, setName] = useState("");
  const items = catalogs?.[ctype] || [];

  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await API.post(`/catalogs/${ctype}`, { name: name.trim(), color: withColor ? Math.floor(Math.random() * 11) + 1 : undefined });
      setName(""); refreshCatalogs(); toast.success("Added");
    } catch (err) { toast.error(apiErr(err)); }
  };

  const toggle = async (item) => {
    await API.patch(`/catalogs/${ctype}/${item.id}`, { active: item.active === false });
    refreshCatalogs();
  };

  const rename = async (item) => {
    const n = window.prompt("Rename:", item.name);
    if (n && n !== item.name) {
      await API.patch(`/catalogs/${ctype}/${item.id}`, { name: n });
      refreshCatalogs();
    }
  };

  return (
    <div className="hivf-card p-4">
      <h3 className="font-display text-sm font-extrabold text-slate-800">{title} ({items.length})</h3>
      <form onSubmit={add} className="mt-3 flex gap-2">
        <input data-testid={`add-${ctype}-input`} className="hivf-input !w-64" placeholder={`New ${title.toLowerCase().replace(/s$/, "")}…`} value={name} onChange={(e) => setName(e.target.value)} />
        <button data-testid={`add-${ctype}-button`} type="submit" className="hivf-btn-primary !py-2"><Plus size={14} /> Add</button>
      </form>
      <div className="mt-4 flex flex-wrap gap-2" data-testid={`${ctype}-list`}>
        {items.map((t) => (
          <span key={t.id} className={`group inline-flex items-center gap-1 ${t.active === false ? "opacity-40" : ""}`}>
            {withColor ? <TagChip tag={t} /> : <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">{t.name}</span>}
            <button onClick={() => rename(t)} className="hidden text-[10px] font-bold text-slate-400 group-hover:inline">edit</button>
            <button onClick={() => toggle(t)} className="hidden text-[10px] font-bold text-slate-400 group-hover:inline">{t.active === false ? "enable" : "disable"}</button>
          </span>
        ))}
      </div>
    </div>
  );
}

function DropdownsTab() {
  return (
    <div className="space-y-4">
      <CatalogTab ctype="lead_stage" title="Lead Stages" />
      <CatalogTab ctype="follow_up_tag" title="Follow-up Tags" />
      <CatalogTab ctype="lost_reason" title="Lost Reasons" />
      <CatalogTab ctype="source_lead" title="Lead Sources" />
      <CatalogTab ctype="stage" title="Pipeline Stages (Odoo)" />
      <CatalogTab ctype="utm_source" title="UTM Sources" />
      <CatalogTab ctype="utm_medium" title="UTM Mediums" />
      <CatalogTab ctype="utm_campaign" title="UTM Campaigns" />
      <CatalogTab ctype="activity_type" title="Activity Types" />
    </div>
  );
}

function WebhooksTab() {
  const { catalogs } = useCatalogs();
  const [hooks, setHooks] = useState(null);
  const [name, setName] = useState("");

  const load = () => API.get("/webhooks").then(({ data }) => setHooks(data));
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await API.post("/webhooks", { name: name.trim() });
      setName(""); load(); toast.success("Webhook created");
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!hooks) return <Spinner />;
  const base = process.env.REACT_APP_BACKEND_URL;
  return (
    <div className="hivf-card p-4">
      <h3 className="font-display text-sm font-extrabold text-slate-800">Lead Capture Webhooks</h3>
      <p className="mt-1 text-xs text-slate-500">Point your landing pages, chatbot, app & forms at these URLs (POST JSON: name, phone, email, state, …). Incoming leads are auto-created & round-robin assigned.</p>
      <form onSubmit={create} className="mt-3 flex gap-2">
        <input data-testid="webhook-name-input" className="hivf-input !w-64" placeholder="e.g. Website Landing Page" value={name} onChange={(e) => setName(e.target.value)} />
        <button data-testid="webhook-create-button" type="submit" className="hivf-btn-primary !py-2"><Plus size={14} /> Create</button>
      </form>
      <div className="mt-4 space-y-2" data-testid="webhooks-list">
        {hooks.map((h) => (
          <div key={h.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-100 p-3">
            <div className="min-w-40">
              <p className="text-sm font-bold text-slate-700">{h.name}</p>
              <p className="text-[11px] text-slate-400">{h.hits || 0} leads captured · {h.active ? "active" : "disabled"}</p>
            </div>
            <code className="flex-1 truncate rounded-lg bg-slate-50 px-2 py-1.5 text-[11px] text-slate-600">{base}/api/webhook/lead/{h.token}</code>
            <button title="Copy URL" onClick={() => { navigator.clipboard.writeText(`${base}/api/webhook/lead/${h.token}`); toast.success("Copied"); }} className="text-slate-400 hover:text-[#4A90E2]"><Copy size={16} /></button>
            <button onClick={async () => { await API.patch(`/webhooks/${h.id}`, { active: !h.active }); load(); }} className="text-xs font-bold text-slate-400">{h.active ? "Disable" : "Enable"}</button>
            <button onClick={async () => { if (window.confirm("Delete webhook?")) { await API.delete(`/webhooks/${h.id}`); load(); } }} className="text-slate-300 hover:text-rose-500"><Trash size={16} /></button>
          </div>
        ))}
        {hooks.length === 0 && <p className="py-6 text-center text-sm text-slate-400">No webhooks yet — create your first one above.</p>}
      </div>
    </div>
  );
}

function AutomationsTab() {
  const { catalogs } = useCatalogs();
  const [rules, setRules] = useState(null);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ name: "", trigger: "on_create", tag_id: "", action_type: "send_whatsapp_template", action_value: "", lead_stage: "" });
  const [waTemplates, setWaTemplates] = useState([]);
  const [emailTemplates, setEmailTemplates] = useState([]);

  const load = () => API.get("/admin/automations").then(({ data }) => setRules(data));
  useEffect(() => {
    load();
    API.get("/templates/whatsapp").then(({ data }) => setWaTemplates(data));
    API.get("/templates/email").then(({ data }) => setEmailTemplates(data));
  }, []);

  const create = async (e) => {
    e.preventDefault();
    const condition = {};
    if (form.trigger === "on_tag_set" && form.tag_id) condition.tag_id = parseInt(form.tag_id);
    if (form.trigger === "on_stage_set" && form.lead_stage) condition.lead_stage = form.lead_stage;
    const action = { type: form.action_type };
    if (["send_whatsapp_template", "send_email_template"].includes(form.action_type)) action.value = parseInt(form.action_value) || form.action_value;
    else if (form.action_type === "add_tag") action.value = parseInt(form.action_value);
    else action.value = form.action_value;
    try {
      await API.post("/admin/automations", { name: form.name, trigger: form.trigger, condition, actions: [action] });
      toast.success("Automation created"); setShow(false); load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!rules) return <Spinner />;
  return (
    <div className="hivf-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-sm font-extrabold text-slate-800">Automation Rules</h3>
          <p className="text-xs text-slate-500">Replicates your Odoo automations (welcome WhatsApp/email on new lead, tag triggers…). Template sends queue until live APIs are connected.</p>
        </div>
        <button data-testid="add-automation-button" onClick={() => setShow(true)} className="hivf-btn-primary !py-1.5 text-xs"><Plus size={14} /> New rule</button>
      </div>
      <div className="mt-4 space-y-2" data-testid="automations-list">
        {rules.map((r) => (
          <div key={r.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3">
            <div className="flex-1">
              <p className="text-sm font-bold text-slate-700">{r.name}</p>
              <p className="text-[11px] text-slate-400">
                Trigger: {r.trigger} {r.condition?.tag_id ? `(tag #${r.condition.tag_id})` : ""}{r.condition?.lead_stage ? `(stage ${r.condition.lead_stage})` : ""} → {(r.actions || []).map((a) => a.type).join(", ")}
              </p>
            </div>
            <button onClick={async () => { await API.patch(`/admin/automations/${r.id}`, { active: !r.active }); load(); }}
              className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${r.active ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              {r.active ? "ACTIVE" : "OFF"}
            </button>
            <button onClick={async () => { if (window.confirm("Delete rule?")) { await API.delete(`/admin/automations/${r.id}`); load(); } }} className="text-slate-300 hover:text-rose-500"><Trash size={16} /></button>
          </div>
        ))}
        {rules.length === 0 && <p className="py-6 text-center text-sm text-slate-400">No automation rules yet.</p>}
      </div>
      {show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setShow(false)}>
          <form onSubmit={create} onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" data-testid="automation-modal">
            <h3 className="font-display text-lg font-extrabold">New Automation</h3>
            <div className="mt-4 space-y-3">
              <input required className="hivf-input" placeholder="Rule name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} data-testid="automation-name-input" />
              <select className="hivf-select w-full" value={form.trigger} onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value }))}>
                <option value="on_create">When lead is created</option>
                <option value="on_tag_set">When tag is added</option>
                <option value="on_stage_set">When stage changes</option>
              </select>
              {form.trigger === "on_tag_set" && (
                <select className="hivf-select w-full" value={form.tag_id} onChange={(e) => setForm((f) => ({ ...f, tag_id: e.target.value }))}>
                  <option value="">Any tag…</option>
                  {(catalogs?.tag || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
              {form.trigger === "on_stage_set" && (
                <select className="hivf-select w-full" value={form.lead_stage} onChange={(e) => setForm((f) => ({ ...f, lead_stage: e.target.value }))}>
                  <option value="">Any stage…</option>
                  {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                </select>
              )}
              <select className="hivf-select w-full" value={form.action_type} onChange={(e) => setForm((f) => ({ ...f, action_type: e.target.value, action_value: "" }))}>
                <option value="send_whatsapp_template">Send WhatsApp template</option>
                <option value="send_email_template">Send Email template</option>
                <option value="add_tag">Add tag</option>
                <option value="set_lead_stage">Set lead stage</option>
              </select>
              {form.action_type === "send_whatsapp_template" && (
                <select required className="hivf-select w-full" value={form.action_value} onChange={(e) => setForm((f) => ({ ...f, action_value: e.target.value }))}>
                  <option value="">Choose template…</option>
                  {waTemplates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
              {form.action_type === "send_email_template" && (
                <select required className="hivf-select w-full" value={form.action_value} onChange={(e) => setForm((f) => ({ ...f, action_value: e.target.value }))}>
                  <option value="">Choose template…</option>
                  {emailTemplates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
              {form.action_type === "add_tag" && (
                <select required className="hivf-select w-full" value={form.action_value} onChange={(e) => setForm((f) => ({ ...f, action_value: e.target.value }))}>
                  <option value="">Choose tag…</option>
                  {(catalogs?.tag || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
              {form.action_type === "set_lead_stage" && (
                <select required className="hivf-select w-full" value={form.action_value} onChange={(e) => setForm((f) => ({ ...f, action_value: e.target.value }))}>
                  <option value="">Choose stage…</option>
                  {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                </select>
              )}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setShow(false)} className="hivf-btn-secondary">Cancel</button>
              <button type="submit" className="hivf-btn-primary" data-testid="automation-submit">Create</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function AssignmentTab() {
  const { catalogs } = useCatalogs();
  const [settings, setSettings] = useState(null);

  useEffect(() => {
    API.get("/admin/settings").then(({ data }) => setSettings(data.assignment || { enabled: false, user_ids: [] }));
  }, []);

  const save = async (next) => {
    setSettings(next);
    await API.patch("/admin/settings", { key: "assignment", value: { enabled: next.enabled, user_ids: next.user_ids, pointer: next.pointer || 0 } });
    toast.success("Saved");
  };

  if (!settings) return <Spinner />;
  const callers = (catalogs?.users || []).filter((u) => u.active);
  return (
    <div className="hivf-card p-4" data-testid="assignment-settings">
      <h3 className="font-display text-sm font-extrabold text-slate-800">Round-robin Auto Assignment</h3>
      <p className="mt-1 text-xs text-slate-500">Incoming webhook leads get distributed across the selected callers automatically.</p>
      <label className="mt-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
        <input type="checkbox" data-testid="assignment-enabled-checkbox" checked={!!settings.enabled} onChange={(e) => save({ ...settings, enabled: e.target.checked })} />
        Enable auto-assignment
      </label>
      <div className="mt-3 grid grid-cols-2 gap-1.5 md:grid-cols-3">
        {callers.map((u) => (
          <label key={u.id} className="flex items-center gap-2 rounded-lg border border-slate-100 px-2 py-1.5 text-sm text-slate-600">
            <input type="checkbox" checked={(settings.user_ids || []).includes(u.id)}
              onChange={(e) => save({ ...settings, user_ids: e.target.checked ? [...(settings.user_ids || []), u.id] : settings.user_ids.filter((x) => x !== u.id) })} />
            {u.name} <span className="text-[10px] text-slate-400">({u.role})</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function MigrationTab() {
  const [status, setStatus] = useState(null);
  const [audit, setAudit] = useState(null);
  const [auditing, setAuditing] = useState(false);
  const load = () => API.get("/admin/migration/status").then(({ data }) => setStatus(data));
  useEffect(() => {
    load();
    API.get("/admin/settings").then(({ data }) => data.last_audit && setAudit(data.last_audit));
  }, []);

  const runAudit = async () => {
    setAuditing(true);
    try {
      const { data } = await API.post("/admin/migration/audit");
      setAudit(data);
      toast.success(data.all_match ? "Audit passed — everything matches Odoo ✓" : "Audit complete — review differences below");
    } catch (e) {
      toast.error(apiErr(e));
    } finally { setAuditing(false); }
  };

  if (!status) return <Spinner />;
  return (
    <div className="space-y-4">
      <div className="hivf-card p-4" data-testid="migration-audit">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-display text-sm font-extrabold text-slate-800">Odoo vs CRM — Live Audit</h3>
            <p className="text-xs text-slate-500">Connects to your Odoo right now, counts every entity there, and compares with this CRM — your proof that nothing was missed.</p>
          </div>
          <button data-testid="run-audit-button" onClick={runAudit} disabled={auditing} className="hivf-btn-primary !py-1.5 text-xs">
            {auditing ? "Auditing… (~20s)" : "Run Audit vs Odoo"}
          </button>
        </div>
        {audit && (
          <>
            <p className="mt-3 text-xs text-slate-400">Last run: {audit.ran_at} UTC · {audit.all_match ? <span className="font-bold text-emerald-600">ALL ENTITIES MATCH ✓</span> : <span className="font-bold text-amber-600">differences found (see notes)</span>}</p>
            <table className="mt-2 w-full text-sm" data-testid="audit-table">
              <thead><tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-2">Entity</th><th className="py-2 text-right">In Odoo</th><th className="py-2 text-right">In CRM</th><th className="py-2 text-center">Status</th><th className="py-2">Note</th></tr></thead>
              <tbody>
                {audit.rows.map((r) => (
                  <tr key={r.entity} className="border-b border-slate-50">
                    <td className="py-1.5 font-semibold text-slate-700">{r.entity.replace(/_/g, " ")}</td>
                    <td className="py-1.5 text-right text-slate-600">{r.odoo >= 0 ? r.odoo.toLocaleString("en-IN") : "n/a"}</td>
                    <td className="py-1.5 text-right text-slate-600">{r.crm.toLocaleString("en-IN")}</td>
                    <td className="py-1.5 text-center">{r.match ? <span className="font-bold text-emerald-500">✓</span> : <span className="font-bold text-rose-500">✗</span>}</td>
                    <td className="py-1.5 text-[11px] text-slate-400">{r.note || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="hivf-card p-4" data-testid="migration-status">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Odoo Data Migration</h3>
        <button onClick={load} className="hivf-btn-secondary !py-1.5 text-xs"><ArrowsClockwise size={14} /> Refresh</button>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {Object.entries(status.counts || {}).map(([k, v]) => (
          <div key={k} className="rounded-xl bg-slate-50 p-3 text-center">
            <p className="font-display text-lg font-extrabold text-slate-800">{v.toLocaleString("en-IN")}</p>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{k.replace(/_/g, " ")}</p>
          </div>
        ))}
      </div>
      <table className="mt-4 w-full text-sm">
        <thead><tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wider text-slate-400">
          <th className="py-2">Entity</th><th className="py-2">Status</th><th className="py-2 text-right">Progress</th><th className="py-2 text-right">Updated</th></tr></thead>
        <tbody>
          {(status.entities || []).map((e) => (
            <tr key={e.entity} className="border-b border-slate-50">
              <td className="py-2 font-semibold text-slate-700">{e.entity}</td>
              <td className="py-2">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${e.state === "done" ? "bg-emerald-50 text-emerald-600" : e.state === "error" ? "bg-rose-50 text-rose-600" : "bg-amber-50 text-amber-600"}`}>{e.state}</span>
              </td>
              <td className="py-2 text-right text-slate-600">{e.done?.toLocaleString("en-IN") || 0}{e.total ? ` / ${e.total.toLocaleString("en-IN")}` : ""}</td>
              <td className="py-2 text-right text-xs text-slate-400">{e.updated_at?.slice(0, 19).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
