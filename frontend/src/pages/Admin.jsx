import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash, ArrowsClockwise, Copy, Phone, DotsSixVertical, FacebookLogo, WhatsappLogo, EnvelopeSimple, GoogleLogo, PencilSimple, LockSimple } from "@phosphor-icons/react";
import { API, apiErr, fmtDate } from "../lib/api";
import { useAuth, useCatalogs, useCatalogMaps } from "../context/AuthContext";
import { Spinner, TagChip } from "../components/Bits";

const TABS = ["Users", "Tags", "Dropdowns", "Custom Fields", "Webhooks", "Automations", "Assignment", "Telephony", "Facebook", "WhatsApp", "Email", "Migration"];

export default function Admin() {
  const { user } = useAuth();
  const [tab, setTab] = useState("Users");
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("tab")) setTab(p.get("tab"));
    if (p.get("gmail") === "connected") toast.success("Gmail connected — live email is now active ✓");
    else if (p.get("gmail")) toast.error(`Gmail connection failed${p.get("reason") ? " — " + p.get("reason") : " — check redirect URI & consent"}`, { duration: 12000 });
  }, []);
  return (
    <div className="p-6" data-testid="admin-page">
      <h1 className="font-display text-2xl font-extrabold text-slate-900">Admin</h1>
      <p className="text-sm text-slate-500">Manage everything that powers your CRM</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t} data-testid={`admin-tab-${t.toLowerCase().replace(/\s/g, "-")}`} onClick={() => setTab(t)}
            className={`rounded-full border px-4 py-2 text-sm font-bold transition-colors ${tab === t ? "border-[#4A90E2] bg-[#4A90E2]/10 text-[#357ABD]" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="mt-5">
        {tab === "Users" && <UsersTab isAdmin={user.role === "admin"} />}
        {tab === "Tags" && <CatalogTab ctype="tag" title="Disposition Tags" withColor />}
        {tab === "Dropdowns" && <DropdownsTab />}
        {tab === "Custom Fields" && <CustomFieldsTab />}
        {tab === "Webhooks" && <WebhooksTab />}
        {tab === "Automations" && <AutomationsTab />}
        {tab === "Assignment" && <AssignmentTab />}
        {tab === "Telephony" && <TelephonyTab isAdmin={user.role === "admin"} />}
        {tab === "Facebook" && <FacebookTab isAdmin={user.role === "admin"} />}
        {tab === "WhatsApp" && <WhatsAppTab isAdmin={user.role === "admin"} />}
        {tab === "Email" && <EmailTab isAdmin={user.role === "admin"} />}
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

  const remove = async (u) => {
    if (!window.confirm(`Delete user "${u.name}" permanently? (If they have active leads, reassign or deactivate instead.)`)) return;
    try {
      await API.delete(`/users/${u.id}`);
      toast.success("User deleted");
      load(); refreshCatalogs();
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!users) return <Spinner />;
  return (
    <div className="space-y-4">
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
                  <button className="mr-2 text-xs font-bold text-slate-400" onClick={() => patch(u.id, { active: !u.active })}>{u.active ? "Deactivate" : "Activate"}</button>
                  <button className="text-xs font-bold text-rose-500" data-testid={`delete-user-${u.id}`} onClick={() => remove(u)}>Delete</button>
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
      <RolesAccessControl isAdmin={isAdmin} />
    </div>
  );
}

function RolesAccessControl({ isAdmin }) {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  const load = () => API.get("/admin/role-permissions").then(({ data }) => setData(data));
  useEffect(() => { load(); }, []);
  if (!data) return null;

  const roles = ["admin", "manager", "caller"];
  const groups = [["Module access", data.module_perms], ["Actions & data scope", data.action_perms]];

  const toggle = (role, perm) => {
    if (!isAdmin || role === "admin") return;
    setData((d) => ({ ...d, matrix: { ...d.matrix, [role]: { ...d.matrix[role], [perm]: !d.matrix[role][perm] } } }));
  };
  const save = async () => {
    setSaving(true);
    try {
      const { data: res } = await API.patch("/admin/role-permissions", { matrix: { manager: data.matrix.manager, caller: data.matrix.caller } });
      setData((d) => ({ ...d, matrix: res.matrix }));
      toast.success("Access control saved — users will see it on next login/refresh");
    } catch (e) { toast.error(apiErr(e)); } finally { setSaving(false); }
  };

  return (
    <div className="hivf-card p-4" data-testid="roles-access-control">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-sm font-extrabold text-slate-800">Roles &amp; Access Control</h3>
          <p className="mt-1 text-xs text-slate-500">Define what each role can see and do. Admin always has full access. Changes apply on the user's next login or refresh.</p>
        </div>
        {isAdmin && <button data-testid="roles-save-button" onClick={save} disabled={saving} className="hivf-btn-primary !py-1.5 text-xs">{saving ? "Saving…" : "Save changes"}</button>}
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm" data-testid="roles-matrix-table">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-2 py-2">Permission</th>
              {roles.map((r) => (
                <th key={r} className="px-2 py-2 text-center capitalize">{r}{r === "admin" && <LockSimple size={11} className="ml-1 inline text-slate-300" />}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map(([gLabel, perms]) => (
              <React.Fragment key={gLabel}>
                <tr className="bg-slate-50"><td colSpan={4} className="px-2 py-1.5 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">{gLabel}</td></tr>
                {perms.map((perm) => (
                  <tr key={perm} className="border-b border-slate-50" data-testid={`perm-row-${perm}`}>
                    <td className="px-2 py-2 font-semibold text-slate-600">{data.labels[perm] || perm}</td>
                    {roles.map((role) => {
                      const checked = !!data.matrix[role][perm];
                      const locked = role === "admin" || !isAdmin;
                      return (
                        <td key={role} className="px-2 py-2 text-center">
                          <input type="checkbox" checked={checked} disabled={locked}
                            onChange={() => toggle(role, perm)} data-testid={`perm-${role}-${perm}`}
                            className={locked ? "cursor-not-allowed opacity-60" : "cursor-pointer accent-[#4A90E2]"} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
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

/* ---------- Case 2: Odoo-Studio-style drag-drop form builder ---------- */
const FIELD_TYPES = [
  { t: "char", label: "Text" },
  { t: "text", label: "Multiline Text" },
  { t: "integer", label: "Integer" },
  { t: "float", label: "Decimal" },
  { t: "monetary", label: "Monetary (₹)" },
  { t: "date", label: "Date" },
  { t: "datetime", label: "Date & Time" },
  { t: "boolean", label: "Checkbox" },
  { t: "selection", label: "Dropdown" },
];
const SECTIONS = [
  { key: "qa", title: "Meta / Google Q&A card" },
  { key: "general", title: "Custom Fields card" },
];

function CustomFieldsTab() {
  const { refreshCatalogs } = useCatalogs();
  const [fields, setFields] = useState(null);
  const [drag, setDrag] = useState(null); // {kind:'new'|'field', type?, id?}
  const [overSection, setOverSection] = useState(null);
  const [modal, setModal] = useState(null); // {section, field_type}

  const load = () => API.get("/catalogs/custom-fields/all").then(({ data }) => setFields(data));
  useEffect(() => { load(); }, []);

  const persistOrder = async (ordered) => {
    setFields(ordered);
    await API.post("/catalogs/custom-fields/reorder", { order: ordered.map((f) => f.id) });
    refreshCatalogs();
  };

  const onDropToSection = async (sectionKey, beforeId = null) => {
    if (!drag) return;
    setOverSection(null);
    if (drag.kind === "new") {
      setModal({ section: sectionKey, field_type: drag.type });
      setDrag(null);
      return;
    }
    // move existing field
    const moving = fields.find((f) => f.id === drag.id);
    if (!moving) { setDrag(null); return; }
    if (moving.section !== sectionKey) {
      await API.patch(`/catalogs/custom-fields/${moving.id}`, { section: sectionKey });
      moving.section = sectionKey;
    }
    const rest = fields.filter((f) => f.id !== moving.id);
    let idx = rest.length;
    if (beforeId != null) { const i = rest.findIndex((f) => f.id === beforeId); if (i >= 0) idx = i; }
    rest.splice(idx, 0, moving);
    await persistOrder(rest);
    setDrag(null);
  };

  const toggle = async (f) => { await API.patch(`/catalogs/custom-fields/${f.id}`, { active: f.active === false }); load(); refreshCatalogs(); };
  const del = async (f) => { if (window.confirm(`Disable field '${f.label}'?`)) { await API.delete(`/catalogs/custom-fields/${f.id}`); load(); refreshCatalogs(); } };
  const hardDelete = async (f) => { if (window.confirm(`Permanently delete '${f.label}'? This removes it from the builder for good.`)) { await API.delete(`/catalogs/custom-fields/${f.id}`, { params: { hard: true } }); load(); refreshCatalogs(); } };

  if (!fields) return <Spinner />;
  const active = fields.filter((f) => f.active !== false);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-4" data-testid="form-builder">
      {/* Components palette */}
      <div className="hivf-card p-4 lg:col-span-1">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Components</h3>
        <p className="mt-1 text-[11px] text-slate-400">Drag a field type onto a card → or click to add.</p>
        <div className="mt-3 space-y-1.5" data-testid="components-palette">
          {FIELD_TYPES.map((ft) => (
            <div key={ft.t} draggable data-testid={`palette-${ft.t}`}
              onDragStart={() => setDrag({ kind: "new", type: ft.t })}
              onDragEnd={() => setDrag(null)}
              onClick={() => setModal({ section: "general", field_type: ft.t })}
              className="flex cursor-grab items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600 transition-colors hover:border-[#4A90E2] hover:bg-[#4A90E2]/5 active:cursor-grabbing">
              <DotsSixVertical size={14} className="text-slate-300" /> {ft.label}
            </div>
          ))}
        </div>
      </div>

      {/* Form canvas */}
      <div className="space-y-4 lg:col-span-3">
        {SECTIONS.map((sec) => {
          const secFields = active.filter((f) => f.section === sec.key);
          return (
            <div key={sec.key}
              onDragOver={(e) => { e.preventDefault(); setOverSection(sec.key); }}
              onDragLeave={() => setOverSection((s) => (s === sec.key ? null : s))}
              onDrop={(e) => { e.preventDefault(); onDropToSection(sec.key); }}
              data-testid={`section-dropzone-${sec.key}`}
              className={`hivf-card p-4 transition-colors ${overSection === sec.key ? "ring-2 ring-[#4A90E2] ring-offset-1" : ""}`}>
              <h3 className="font-display text-sm font-extrabold text-slate-800">{sec.title} <span className="text-[11px] font-normal text-slate-400">({secFields.length})</span></h3>
              <div className="mt-3 space-y-2 min-h-[56px]" data-testid={`section-fields-${sec.key}`}>
                {secFields.length === 0 && (
                  <div className="rounded-xl border-2 border-dashed border-slate-200 py-6 text-center text-xs text-slate-400">Drag a component here</div>
                )}
                {secFields.map((f) => (
                  <div key={f.id} draggable data-testid={`field-card-${f.id}`}
                    onDragStart={() => setDrag({ kind: "field", id: f.id })}
                    onDragEnd={() => setDrag(null)}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDrop={(e) => { e.preventDefault(); e.stopPropagation(); onDropToSection(sec.key, f.id); }}
                    className="flex items-center gap-3 rounded-xl border border-slate-100 bg-white p-3 shadow-sm">
                    <DotsSixVertical size={16} className="shrink-0 cursor-grab text-slate-300" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-bold text-slate-700">{f.label}</p>
                      <p className="text-[11px] text-slate-400">
                        {FIELD_TYPES.find((t) => t.t === f.field_type)?.label || f.field_type}
                        {f.field_type === "selection" && (f.options || []).length > 0 && ` · ${f.options.join(", ")}`}
                        {(f.aliases || []).length > 0 && ` · aliases: ${f.aliases.join(", ")}`}
                      </p>
                    </div>
                    <code className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-400">{f.key}</code>
                    <button onClick={() => setModal({ section: f.section, field_type: f.field_type, field: f })} data-testid={`edit-field-${f.id}`} className="text-slate-300 hover:text-[#4A90E2]"><PencilSimple size={15} /></button>
                    <button onClick={() => del(f)} className="text-slate-300 hover:text-rose-500"><Trash size={15} /></button>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {fields.some((f) => f.active === false) && (
          <div className="hivf-card p-4">
            <h3 className="font-display text-xs font-extrabold uppercase tracking-wider text-slate-400">Disabled fields</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {fields.filter((f) => f.active === false).map((f) => (
                <span key={f.id} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold text-slate-400" data-testid={`disabled-field-${f.id}`}>
                  <button onClick={() => toggle(f)} className="hover:text-emerald-600" data-testid={`reenable-field-${f.id}`}>{f.label} · enable</button>
                  <button onClick={() => hardDelete(f)} className="hover:text-rose-500" data-testid={`harddelete-field-${f.id}`} title="Delete permanently"><Trash size={12} /></button>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {modal && <AddFieldModal section={modal.section} fieldType={modal.field_type} field={modal.field} onClose={() => setModal(null)}
        onCreated={() => { setModal(null); load(); refreshCatalogs(); }} />}
    </div>
  );
}

function AddFieldModal({ section, fieldType, field, onClose, onCreated }) {
  const isEdit = !!field;
  const [form, setForm] = useState({
    label: field?.label || "",
    field_type: field?.field_type || fieldType || "char",
    section: field?.section || section,
    options: (field?.options || []).join(", "),
    aliases: (field?.aliases || []).join(", "),
  });
  const create = async (e) => {
    e.preventDefault();
    if (!form.label.trim()) return;
    const payload = {
      label: form.label.trim(),
      field_type: form.field_type,
      options: form.field_type === "selection" ? form.options.split(",").map((s) => s.trim()).filter(Boolean) : [],
      section: form.section,
      aliases: form.aliases.split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (isEdit) {
        await API.patch(`/catalogs/custom-fields/${field.id}`, payload);
        toast.success("Field updated");
      } else {
        await API.post("/catalogs/custom-fields/create", payload);
        toast.success("Field added — it now shows on every lead");
      }
      onCreated();
    } catch (err) { toast.error(apiErr(err)); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={create} onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" data-testid="add-field-modal">
        <h3 className="font-display text-lg font-extrabold">{isEdit ? "Edit Field" : "New Field"}</h3>
        <div className="mt-4 space-y-3">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Field label</label>
            <input data-testid="field-label-input" required autoFocus className="hivf-input mt-1" placeholder="e.g. Preferred Clinic Location"
              value={form.label} onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Type</label>
              <select data-testid="field-type-select" className="hivf-select mt-1 w-full" value={form.field_type} onChange={(e) => setForm((f) => ({ ...f, field_type: e.target.value }))}>
                {FIELD_TYPES.map((ft) => <option key={ft.t} value={ft.t}>{ft.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Show under</label>
              <select data-testid="field-section-select" className="hivf-select mt-1 w-full" value={form.section} onChange={(e) => setForm((f) => ({ ...f, section: e.target.value }))}>
                {SECTIONS.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
              </select>
            </div>
          </div>
          {form.field_type === "selection" && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Dropdown options (comma-separated)</label>
              <input data-testid="field-options-input" className="hivf-input mt-1" placeholder="e.g. Delhi, Noida, Gurgaon"
                value={form.options} onChange={(e) => setForm((f) => ({ ...f, options: e.target.value }))} />
            </div>
          )}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Webhook / ads aliases (optional)</label>
            <input data-testid="field-aliases-input" className="hivf-input mt-1" placeholder="e.g. preferred_location, clinic_city"
              value={form.aliases} onChange={(e) => setForm((f) => ({ ...f, aliases: e.target.value }))} />
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button type="submit" className="hivf-btn-primary" data-testid="field-create-submit"><Plus size={14} /> {isEdit ? "Save field" : "Add field"}</button>
        </div>
      </form>
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

      <div className="mt-6 rounded-xl border border-slate-100 bg-slate-50/60 p-4" data-testid="lead-form-guide">
        <h4 className="font-display text-sm font-extrabold text-slate-800">📘 Website / Google Ads Lead Form — Setup Guide</h4>
        <p className="mt-1 text-xs text-slate-500">Send a POST request (JSON or form-encoded) to your webhook URL above. These standard field names are auto-mapped:</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {["name", "phone", "email", "city", "state", "gender", "male_age", "female_age", "query", "campaign_name", "ads_platform", "ads_name"].map((f) => (
            <code key={f} className="rounded bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200">{f}</code>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">Any extra fields are saved under the lead's custom data. To map a specific extra field, create it in <b>Admin → Custom Fields</b> (matching the form field name).</p>
        <p className="mt-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">Sample HTML lead form</p>
        <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-emerald-200" data-testid="lead-form-sample">{`<form id="leadForm">
  <input name="name" placeholder="Full name" required />
  <input name="phone" placeholder="Phone" required />
  <input name="email" placeholder="Email" />
  <input name="city" placeholder="City" />
  <select name="state">...</select>
  <button type="submit">Submit</button>
</form>
<script>
leadForm.onsubmit = async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(leadForm));
  await fetch("${base}/api/webhook/lead/${hooks[0]?.token || "YOUR_TOKEN"}", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  alert("Thank you! We'll call you shortly.");
};
</script>`}</pre>
        <button onClick={() => { navigator.clipboard.writeText(document.querySelector('[data-testid="lead-form-sample"]').innerText); toast.success("Sample form copied"); }}
          className="mt-2 text-xs font-bold text-[#357ABD]" data-testid="copy-sample-form">Copy sample form</button>
      </div>
    </div>
  );
}

function AutomationsTab() {
  const { catalogs } = useCatalogs();
  const [rules, setRules] = useState(null);
  const [show, setShow] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({ name: "", trigger: "on_create", tag_id: "", lead_stage: "", actions: [{ type: "send_whatsapp_template", value: "" }] });
  const [waTemplates, setWaTemplates] = useState([]);
  const [emailTemplates, setEmailTemplates] = useState([]);

  const load = () => API.get("/admin/automations").then(({ data }) => setRules(data));
  useEffect(() => {
    load();
    API.get("/templates/whatsapp").then(({ data }) => setWaTemplates(data));
    API.get("/templates/email").then(({ data }) => setEmailTemplates(data));
  }, []);

  const resetForm = () => { setForm({ name: "", trigger: "on_create", tag_id: "", lead_stage: "", actions: [{ type: "send_whatsapp_template", value: "" }] }); setEditId(null); };
  const closeModal = () => { setShow(false); resetForm(); };

  const startEdit = (r) => {
    setEditId(r.id);
    setForm({
      name: r.name || "",
      trigger: r.trigger || "on_create",
      tag_id: r.condition?.tag_id ? String(r.condition.tag_id) : "",
      lead_stage: r.condition?.lead_stage || "",
      actions: (r.actions || []).length ? r.actions.map((a) => ({ type: a.type, value: String(a.value) })) : [{ type: "send_whatsapp_template", value: "" }],
    });
    setShow(true);
  };

  const create = async (e) => {
    e.preventDefault();
    const condition = {};
    if (form.trigger === "on_tag_set" && form.tag_id) condition.tag_id = parseInt(form.tag_id);
    if (form.trigger === "on_stage_set" && form.lead_stage) condition.lead_stage = form.lead_stage;
    const actions = form.actions
      .filter((a) => a.value !== "" && a.value != null)
      .map((a) => ({
        type: a.type,
        value: ["send_whatsapp_template", "send_email_template", "add_tag", "assign_user"].includes(a.type)
          ? (parseInt(a.value) || a.value) : a.value,
      }));
    if (!actions.length) { toast.error("Add at least one action"); return; }
    try {
      if (editId) {
        await API.patch(`/admin/automations/${editId}`, { name: form.name, trigger: form.trigger, condition, actions });
        toast.success("Automation updated");
      } else {
        await API.post("/admin/automations", { name: form.name, trigger: form.trigger, condition, actions });
        toast.success("Automation created");
      }
      closeModal();
      load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const addAction = () => setForm((f) => ({ ...f, actions: [...f.actions, { type: "add_tag", value: "" }] }));
  const removeAction = (idx) => setForm((f) => ({ ...f, actions: f.actions.filter((_, i) => i !== idx) }));
  const updateAction = (idx, patch) => setForm((f) => ({ ...f, actions: f.actions.map((a, i) => (i === idx ? { ...a, ...patch } : a)) }));

  if (!rules) return <Spinner />;
  return (
    <div className="hivf-card p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-sm font-extrabold text-slate-800">Automation Rules</h3>
          <p className="text-xs text-slate-500">Replicates your Odoo automations (welcome WhatsApp/email on new lead, tag triggers…). Template sends queue until live APIs are connected.</p>
        </div>
        <button data-testid="add-automation-button" onClick={() => { resetForm(); setShow(true); }} className="hivf-btn-primary !py-1.5 text-xs"><Plus size={14} /> New rule</button>
      </div>
      <div className="mt-4 space-y-2" data-testid="automations-list">
        {rules.map((r) => (
          <div key={r.id} data-testid={`automation-rule-${r.id}`} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3">
            <div className="flex-1">
              <p className="text-sm font-bold text-slate-700">{r.name}</p>
              <p className="text-[11px] text-slate-400">
                Trigger: {r.trigger} {r.condition?.tag_id ? `(tag #${r.condition.tag_id})` : ""}{r.condition?.lead_stage ? `(stage ${r.condition.lead_stage})` : ""} → {(r.actions || []).map((a) => a.type).join(", ")}
              </p>
            </div>
            <button data-testid={`automation-toggle-${r.id}`} onClick={async () => { await API.patch(`/admin/automations/${r.id}`, { active: !r.active }); load(); }}
              className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${r.active ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
              {r.active ? "ACTIVE" : "OFF"}
            </button>
            <button data-testid={`automation-edit-${r.id}`} onClick={() => startEdit(r)} className="text-slate-300 hover:text-[#4A90E2]"><PencilSimple size={16} /></button>
            <button data-testid={`automation-delete-${r.id}`} onClick={async () => { if (window.confirm("Delete rule?")) { await API.delete(`/admin/automations/${r.id}`); load(); } }} className="text-slate-300 hover:text-rose-500"><Trash size={16} /></button>
          </div>
        ))}
        {rules.length === 0 && <p className="py-6 text-center text-sm text-slate-400">No automation rules yet.</p>}
      </div>
      {show && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={closeModal}>
          <form onSubmit={create} onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" data-testid="automation-modal">
            <h3 className="font-display text-lg font-extrabold">{editId ? "Edit Automation" : "New Automation"}</h3>
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
              <div className="space-y-2 rounded-xl bg-slate-50 p-3">
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Actions to do (runs all, in order)</label>
                {form.actions.map((a, idx) => (
                  <div key={idx} className="flex gap-2" data-testid={`action-row-${idx}`}>
                    <select className="hivf-select flex-1" value={a.type} onChange={(e) => updateAction(idx, { type: e.target.value, value: "" })} data-testid={`action-type-${idx}`}>
                      <option value="send_whatsapp_template">Send WhatsApp template</option>
                      <option value="send_email_template">Send Email template</option>
                      <option value="add_tag">Add tag</option>
                      <option value="set_lead_stage">Set lead stage</option>
                      <option value="assign_user">Assign to user</option>
                    </select>
                    <select required className="hivf-select flex-1" value={a.value} onChange={(e) => updateAction(idx, { value: e.target.value })} data-testid={`action-value-${idx}`}>
                      <option value="">Choose…</option>
                      {a.type === "send_whatsapp_template" && waTemplates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                      {a.type === "send_email_template" && emailTemplates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                      {a.type === "add_tag" && (catalogs?.tag || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                      {a.type === "set_lead_stage" && (catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                      {a.type === "assign_user" && (catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                    </select>
                    {form.actions.length > 1 && (
                      <button type="button" onClick={() => removeAction(idx)} className="shrink-0 text-slate-300 hover:text-rose-500" data-testid={`remove-action-${idx}`}><Trash size={16} /></button>
                    )}
                  </div>
                ))}
                <button type="button" onClick={addAction} className="text-xs font-bold text-[#357ABD]" data-testid="add-action-row">+ Add another action</button>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={closeModal} className="hivf-btn-secondary">Cancel</button>
              <button type="submit" className="hivf-btn-primary" data-testid="automation-submit">{editId ? "Save" : "Create"}</button>
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

function TelephonyTab({ isAdmin }) {
  const [cfg, setCfg] = useState(null);
  const [users, setUsers] = useState(null);
  const [calls, setCalls] = useState(null);
  const screenPopUrl = `${window.location.origin}/screen-pop`;

  const loadCfg = () => API.get("/admin/settings").then(({ data }) =>
    setCfg(data.ozonetel || { domain: "in1-ccaas-api.ozonetel.com", username: "", api_key: "", campaign_name: "", priority: "" }));
  const loadUsers = () => API.get("/users").then(({ data }) => setUsers(data));
  const loadCalls = () => API.get("/calls", { params: { limit: 20 } }).then(({ data }) => setCalls(data.items));
  useEffect(() => { loadCfg(); loadUsers(); loadCalls(); }, []);

  const saveCfg = async (e) => {
    e.preventDefault();
    try {
      await API.patch("/admin/settings", {
        key: "ozonetel",
        value: {
          domain: (cfg.domain || "in1-ccaas-api.ozonetel.com").trim(),
          username: (cfg.username || "").trim(),
          api_key: (cfg.api_key || "").trim(),
          campaign_name: (cfg.campaign_name || "").trim(),
          priority: (cfg.priority || "").toString().trim(),
        },
      });
      toast.success("Ozonetel settings saved");
    } catch (err) { toast.error(apiErr(err)); }
  };

  const patchUser = async (id, updates) => {
    try { await API.patch(`/users/${id}`, updates); loadUsers(); toast.success("Agent mapping saved"); }
    catch (err) { toast.error(apiErr(err)); }
  };

  if (!cfg) return <Spinner />;
  return (
    <div className="space-y-4" data-testid="telephony-tab">
      <div className="hivf-card p-4">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Ozonetel Telephony</h3>
        <p className="mt-1 text-xs text-slate-500">
          Incoming calls pop the matching lead on the agent's screen. Configure your CloudAgent account below,
          then paste the Screen-Pop URL into Ozonetel (Admin → Settings → Screen Pop URL).
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#4A90E2]/5 p-3">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Screen-Pop URL</span>
          <code className="flex-1 truncate rounded-lg bg-white px-2 py-1.5 text-[11px] text-slate-600" data-testid="screen-pop-url">{screenPopUrl}?phoneNumber=&#123;phoneNumber&#125;&amp;ucid=&#123;ucid&#125;&amp;callerID=&#123;callerID&#125;&amp;did=&#123;did&#125;&amp;agentID=&#123;agentID&#125;&amp;phoneName=&#123;phoneName&#125;</code>
          <button title="Copy URL" onClick={() => { navigator.clipboard.writeText(screenPopUrl); toast.success("Copied"); }} className="text-slate-400 hover:text-[#4A90E2]"><Copy size={16} /></button>
        </div>

        <form onSubmit={saveCfg} className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">API Domain</label>
            <input data-testid="ozonetel-domain-input" disabled={!isAdmin} className="hivf-input mt-1" placeholder="in1-ccaas-api.ozonetel.com"
              value={cfg.domain || ""} onChange={(e) => setCfg((c) => ({ ...c, domain: e.target.value }))} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">CloudAgent Username</label>
            <input data-testid="ozonetel-username-input" disabled={!isAdmin} className="hivf-input mt-1" placeholder="homeivf"
              value={cfg.username || ""} onChange={(e) => setCfg((c) => ({ ...c, username: e.target.value }))} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">API Key</label>
            <input data-testid="ozonetel-apikey-input" type="password" disabled={!isAdmin} className="hivf-input mt-1" placeholder="KK…"
              value={cfg.api_key || ""} onChange={(e) => setCfg((c) => ({ ...c, api_key: e.target.value }))} />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Outbound Campaign (for click-to-dial)</label>
            <input data-testid="ozonetel-campaign-input" disabled={!isAdmin} className="hivf-input mt-1" placeholder="e.g. HomeIVF_Outbound"
              value={cfg.campaign_name || ""} onChange={(e) => setCfg((c) => ({ ...c, campaign_name: e.target.value }))} />
          </div>
          {isAdmin && (
            <div className="md:col-span-2">
              <button data-testid="save-ozonetel-button" type="submit" className="hivf-btn-primary !py-2"><Phone size={14} /> Save Telephony Settings</button>
            </div>
          )}
        </form>
      </div>

      <div className="hivf-card p-4">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Agent Mapping</h3>
        <p className="mt-1 text-xs text-slate-500">Map each CRM agent to their Ozonetel Agent ID (or login name) so incoming calls pop on the right person's screen.</p>
        {!users ? <Spinner /> : (
          <table className="mt-3 w-full text-sm" data-testid="agent-mapping-table">
            <thead><tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="py-2">Agent</th><th className="py-2">Ozonetel Agent ID</th><th className="py-2">Ozonetel Login Name</th></tr></thead>
            <tbody>
              {users.filter((u) => u.active).map((u) => (
                <tr key={u.id} className="border-b border-slate-50">
                  <td className="py-2 font-semibold text-slate-700">{u.name} <span className="text-[10px] text-slate-400">({u.role})</span></td>
                  <td className="py-2">
                    <input data-testid={`agent-id-input-${u.id}`} disabled={!isAdmin} defaultValue={u.ozonetel_agent_id || ""} placeholder="e.g. 84822"
                      onBlur={(e) => { const v = e.target.value.trim(); if (v !== (u.ozonetel_agent_id || "")) patchUser(u.id, { ozonetel_agent_id: v }); }}
                      className="hivf-input !w-36 !py-1 text-xs" />
                  </td>
                  <td className="py-2">
                    <input data-testid={`agent-name-input-${u.id}`} disabled={!isAdmin} defaultValue={u.ozonetel_phone_name || ""} placeholder="e.g. agent1"
                      onBlur={(e) => { const v = e.target.value.trim(); if (v !== (u.ozonetel_phone_name || "")) patchUser(u.id, { ozonetel_phone_name: v }); }}
                      className="hivf-input !w-36 !py-1 text-xs" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="hivf-card p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-sm font-extrabold text-slate-800">Recent Calls</h3>
          <button onClick={loadCalls} className="hivf-btn-secondary !py-1.5 text-xs"><ArrowsClockwise size={14} /> Refresh</button>
        </div>
        {!calls ? <Spinner /> : calls.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-400">No calls logged yet. Calls appear here as Ozonetel routes them.</p>
        ) : (
          <table className="mt-3 w-full text-sm" data-testid="recent-calls-table">
            <thead><tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="py-2">Direction</th><th className="py-2">Number</th><th className="py-2">Lead</th><th className="py-2">Agent</th><th className="py-2">When</th></tr></thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id} className="border-b border-slate-50">
                  <td className="py-2 capitalize text-slate-600">{c.direction}</td>
                  <td className="py-2 text-slate-700">{c.phone || "—"}</td>
                  <td className="py-2">{c.lead_id ? <a className="font-semibold text-[#357ABD]" href={`/leads/${c.lead_id}`}>{c.lead_name || `#${c.lead_id}`}</a> : <span className="text-slate-400">No match</span>}</td>
                  <td className="py-2 text-slate-500">{c.agent_name || c.agent_phone_name || "—"}</td>
                  <td className="py-2 text-xs text-slate-400">{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const FB_CRM_FIELDS = [
  ["contact_name", "Contact Name"], ["phone", "Phone"], ["email_from", "Email"],
  ["city", "City"], ["state_name", "State"], ["gender", "Gender"],
  ["male_age", "Male Age"], ["female_age", "Female Age"], ["query", "Query"],
  ["campaign_name", "Campaign"],
];

function FacebookTab({ isAdmin }) {
  const { catalogs } = useCatalogs();
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  const [maps, setMaps] = useState([]); // [{fb, crm}]
  const [test, setTest] = useState([{ name: "full_name", value: "" }, { name: "phone_number", value: "" }, { name: "email", value: "" }]);
  const [diag, setDiag] = useState(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [recentLeads, setRecentLeads] = useState(null);
  const callbackUrl = `${process.env.REACT_APP_BACKEND_URL}/api/webhooks/facebook`;
  const customFields = (catalogs?.custom_fields || []).filter((f) => f.active !== false);

  const load = () => {
    API.get("/admin/settings").then(({ data }) => {
      const fb = data.facebook || { graph_api_version: "v25.0", source_default: "Meta Lead Ads" };
      setCfg(fb);
      setMaps(Object.entries(fb.field_mapping || {}).map(([k, v]) => ({ fb: k, crm: v })));
    });
    API.get("/admin/facebook/status").then(({ data }) => setStatus(data));
    API.get("/admin/facebook/recent-leads").then(({ data }) => setRecentLeads(data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e?.preventDefault();
    const field_mapping = {};
    maps.forEach((m) => { if (m.fb.trim() && m.crm) field_mapping[m.fb.trim()] = m.crm; });
    try {
      await API.patch("/admin/settings", {
        key: "facebook",
        value: {
          app_id: (cfg.app_id || "").trim(), app_secret: (cfg.app_secret || "").trim(),
          page_id: (cfg.page_id || "").trim(), page_access_token: (cfg.page_access_token || "").trim(),
          verify_token: (cfg.verify_token || "").trim(),
          graph_api_version: (cfg.graph_api_version || "v25.0").trim(),
          source_default: (cfg.source_default || "Meta Lead Ads").trim(),
          field_mapping,
        },
      });
      toast.success("Facebook settings saved"); load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const subscribe = async () => {
    try { const { data } = await API.post("/admin/facebook/subscribe"); toast.success("Page subscribed to leadgen ✓"); console.log(data); diagnose(); }
    catch (err) { toast.error(apiErr(err)); }
  };

  const registerWebhook = async () => {
    try {
      const { data } = await API.post("/admin/facebook/register-webhook", { callback_url: callbackUrl });
      toast.success("Leadgen webhook registered with Meta ✓"); console.log(data); diagnose();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const diagnose = async () => {
    setDiagBusy(true);
    try { const { data } = await API.get("/admin/facebook/diagnose"); setDiag(data); }
    catch (err) { toast.error(apiErr(err)); } finally { setDiagBusy(false); }
  };

  const sendTest = async () => {
    const field_data = test.filter((t) => t.name.trim() && t.value.trim()).map((t) => ({ name: t.name.trim(), values: [t.value.trim()] }));
    if (!field_data.length) { toast.error("Add at least one test field"); return; }
    try {
      const { data } = await API.post("/admin/facebook/test", { field_data, leadgen_id: "MANUAL_TEST" });
      toast.success(`Test lead #${data.lead_id} created — open it to verify mapping`);
      load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!cfg) return <Spinner />;
  return (
    <div className="space-y-4" data-testid="facebook-tab">
      <div className="hivf-card p-4">
        <div className="flex items-center gap-2">
          <FacebookLogo size={20} weight="fill" className="text-[#1877F2]" />
          <h3 className="font-display text-sm font-extrabold text-slate-800">Facebook Lead Ads</h3>
          {status && <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold ${status.configured ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>{status.configured ? "CONFIGURED" : "NOT CONNECTED"}</span>}
          {status && <span className="text-[11px] text-slate-400">· {status.leads_captured} leads captured</span>}
        </div>
        <p className="mt-1 text-xs text-slate-500">Auto-capture leads from your Facebook Page lead forms. Connect your Meta app below, paste the callback URL into Meta, then map the form fields.</p>

        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2 rounded-xl bg-[#1877F2]/5 p-3">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Webhook Callback URL</span>
            <code className="flex-1 truncate rounded-lg bg-white px-2 py-1.5 text-[11px] text-slate-600" data-testid="fb-callback-url">{callbackUrl}</code>
            <button title="Copy" onClick={() => { navigator.clipboard.writeText(callbackUrl); toast.success("Copied"); }} className="text-slate-400 hover:text-[#1877F2]"><Copy size={16} /></button>
          </div>
        </div>

        <form onSubmit={save} className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {[["app_id", "App ID", "text"], ["app_secret", "App Secret", "password"], ["page_id", "Page ID", "text"],
            ["page_access_token", "Page Access Token", "password"], ["verify_token", "Verify Token (you choose)", "text"],
            ["graph_api_version", "Graph API Version", "text"]].map(([k, label, type]) => (
            <div key={k}>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</label>
              <input data-testid={`fb-${k}-input`} type={type} disabled={!isAdmin} className="hivf-input mt-1"
                value={cfg[k] || ""} onChange={(e) => setCfg((c) => ({ ...c, [k]: e.target.value }))} />
            </div>
          ))}
          {isAdmin && (
            <div className="flex flex-wrap items-end gap-2 md:col-span-2">
              <button data-testid="fb-save-button" type="submit" className="hivf-btn-primary !py-2"><FacebookLogo size={14} /> Save Settings</button>
              <button type="button" onClick={subscribe} className="hivf-btn-secondary !py-2" data-testid="fb-subscribe-button">Subscribe Page to leadgen</button>
              <button type="button" onClick={registerWebhook} className="hivf-btn-secondary !py-2" data-testid="fb-register-webhook-button">Register leadgen webhook with Meta</button>
              <button type="button" onClick={diagnose} disabled={diagBusy} className="hivf-btn-secondary !py-2" data-testid="fb-diagnose-button">{diagBusy ? "Checking…" : "Check connection"}</button>
            </div>
          )}
        </form>

        {diag && (
          <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50/70 p-4" data-testid="fb-diagnose-result">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Connection diagnostic</p>
            <div className="mt-2 space-y-1.5">
              {diag.checks.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-sm" data-testid={`fb-diag-check-${i}`}>
                  <span className={c.ok ? "text-emerald-500" : "text-rose-500"}>{c.ok ? "✓" : "✕"}</span>
                  <span className="font-semibold text-slate-700">{c.name}:</span>
                  <span className="text-slate-500">{c.detail}</span>
                </div>
              ))}
            </div>
            {diag.next_step && (
              <p className="mt-3 rounded-lg bg-[#1877F2]/5 p-2.5 text-xs font-semibold text-[#1877F2]" data-testid="fb-diag-next-step">
                Next: {diag.next_step}
              </p>
            )}
            {diag.recent_webhook_deliveries && diag.recent_webhook_deliveries.length > 0 && (
              <div className="mt-3" data-testid="fb-webhook-deliveries">
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Recent webhook deliveries from Meta</p>
                <div className="mt-2 space-y-1.5">
                  {diag.recent_webhook_deliveries.map((d, i) => {
                    const color = d.status === "created" ? "text-emerald-600 bg-emerald-50"
                      : d.status === "rejected" || d.status === "error" ? "text-rose-600 bg-rose-50"
                      : "text-amber-600 bg-amber-50";
                    return (
                      <div key={i} className="rounded-lg border border-slate-100 bg-white p-2 text-xs" data-testid={`fb-delivery-${i}`}>
                        <div className="flex items-center gap-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${color}`}>{d.status}</span>
                          <span className="text-slate-400">{d.at}</span>
                        </div>
                        <p className="mt-1 text-slate-600">{d.detail}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {diag.recent_webhook_deliveries && diag.recent_webhook_deliveries.length === 0 && (
              <p className="mt-3 text-xs text-slate-400" data-testid="fb-no-deliveries">
                No webhook deliveries received yet. If Meta's "Track status" shows <b>webhooks.delivery.rejected</b>, it means the callback was rejected before reaching here — usually the saved App Secret does not match the app delivering the webhook.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="hivf-card p-4" data-testid="fb-recent-leads-card">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-display text-sm font-extrabold text-slate-800">Recently captured Facebook leads</h3>
            <p className="mt-1 text-xs text-slate-500">Every lead captured from Meta, newest first — a direct view (ignores date sort, assignment and caller filters).</p>
          </div>
          <div className="flex items-center gap-2">
            {recentLeads && <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-600" data-testid="fb-recent-total">{recentLeads.total} total</span>}
            <button type="button" onClick={() => API.get("/admin/facebook/recent-leads").then(({ data }) => setRecentLeads(data)).catch(() => {})} className="hivf-btn-secondary !py-1.5 text-xs" data-testid="fb-recent-refresh"><ArrowsClockwise size={13} /> Refresh</button>
          </div>
        </div>
        <div className="mt-3" data-testid="fb-recent-leads-list">
          {!recentLeads || recentLeads.leads.length === 0 ? (
            <p className="text-xs text-slate-400" data-testid="fb-recent-empty">No Facebook leads captured yet. Once a Meta lead is delivered and retrieved successfully, it will appear here.</p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-slate-100">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left">Name</th>
                    <th className="px-3 py-2 text-left">Phone</th>
                    <th className="px-3 py-2 text-left">Form</th>
                    <th className="px-3 py-2 text-left">Assigned</th>
                    <th className="px-3 py-2 text-left">Captured</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {recentLeads.leads.map((l) => (
                    <tr key={l.id} className="border-t border-slate-50 hover:bg-slate-50/60" data-testid={`fb-recent-lead-${l.id}`}>
                      <td className="px-3 py-2 font-semibold text-slate-700">{l.contact_name || l.name || "—"}</td>
                      <td className="px-3 py-2 text-slate-500">{l.phone || "—"}</td>
                      <td className="px-3 py-2 text-slate-500">{l.fb_form_name || "—"}</td>
                      <td className="px-3 py-2 text-slate-500">{l.assigned_to}</td>
                      <td className="px-3 py-2 text-slate-400">{fmtDate(l.create_date_ist || l.create_date)}</td>
                      <td className="px-3 py-2 text-right">
                        <Link to={`/leads/${l.id}`} className="text-xs font-bold text-[#357ABD] hover:underline" data-testid={`fb-recent-open-${l.id}`}>Open →</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="hivf-card p-4">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Field Mapping</h3>
        <p className="mt-1 text-xs text-slate-500">Map each Facebook lead-form field name to a CRM field. Unmapped answers are still saved to the lead's Q&A card. Custom fields you build appear here too.</p>
        <div className="mt-3 space-y-2" data-testid="fb-mapping-list">
          {maps.map((m, idx) => (
            <div key={idx} className="flex items-center gap-2" data-testid={`fb-map-row-${idx}`}>
              <input className="hivf-input !py-1" placeholder="Facebook field (e.g. full_name)" value={m.fb}
                onChange={(e) => setMaps((arr) => arr.map((x, i) => (i === idx ? { ...x, fb: e.target.value } : x)))} data-testid={`fb-map-fbname-${idx}`} />
              <span className="text-slate-400">→</span>
              <select className="hivf-select !py-1 flex-1" value={m.crm} onChange={(e) => setMaps((arr) => arr.map((x, i) => (i === idx ? { ...x, crm: e.target.value } : x)))} data-testid={`fb-map-crm-${idx}`}>
                <option value="">Choose CRM field…</option>
                {FB_CRM_FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                {customFields.map((f) => <option key={f.key} value={f.key}>{f.label} (custom)</option>)}
              </select>
              <button type="button" onClick={() => setMaps((arr) => arr.filter((_, i) => i !== idx))} className="text-slate-300 hover:text-rose-500"><Trash size={15} /></button>
            </div>
          ))}
          <div className="flex gap-2">
            <button type="button" onClick={() => setMaps((arr) => [...arr, { fb: "", crm: "" }])} className="text-xs font-bold text-[#357ABD]" data-testid="fb-add-map">+ Add mapping</button>
            {isAdmin && <button type="button" onClick={save} className="hivf-btn-primary !py-1 text-xs" data-testid="fb-save-mapping">Save mapping</button>}
          </div>
        </div>
      </div>

      <div className="hivf-card p-4">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Test a Lead</h3>
        <p className="mt-1 text-xs text-slate-500">Simulate a Facebook lead to verify your mapping end-to-end (creates a real lead you can delete afterwards).</p>
        <div className="mt-3 space-y-2" data-testid="fb-test-rows">
          {test.map((t, idx) => (
            <div key={idx} className="flex items-center gap-2" data-testid={`fb-test-row-${idx}`}>
              <input className="hivf-input !py-1" placeholder="FB field name" value={t.name} onChange={(e) => setTest((arr) => arr.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))} data-testid={`fb-test-name-${idx}`} />
              <input className="hivf-input !py-1 flex-1" placeholder="Value" value={t.value} onChange={(e) => setTest((arr) => arr.map((x, i) => (i === idx ? { ...x, value: e.target.value } : x)))} data-testid={`fb-test-value-${idx}`} />
              <button type="button" onClick={() => setTest((arr) => arr.filter((_, i) => i !== idx))} className="text-slate-300 hover:text-rose-500"><Trash size={15} /></button>
            </div>
          ))}
          <div className="flex gap-2">
            <button type="button" onClick={() => setTest((arr) => [...arr, { name: "", value: "" }])} className="text-xs font-bold text-[#357ABD]">+ Add field</button>
            <button type="button" onClick={sendTest} className="hivf-btn-primary !py-1 text-xs" data-testid="fb-send-test">Send test lead</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function EmailTab({ isAdmin }) {
  const [status, setStatus] = useState(null);
  const [testTo, setTestTo] = useState("");
  const load = () => API.get("/admin/gmail/status").then(({ data }) => setStatus(data)).catch(() => setStatus({ connected: false }));
  useEffect(() => { load(); }, []);

  const connect = async () => {
    try {
      const origin = process.env.REACT_APP_BACKEND_URL;
      const { data } = await API.get("/admin/gmail/auth-url", { params: { origin } });
      window.location.href = data.url;
    }
    catch (e) { toast.error(apiErr(e)); }
  };
  const disconnect = async () => {
    if (!window.confirm("Disconnect Gmail? Emails will queue until reconnected.")) return;
    await API.post("/admin/gmail/disconnect"); toast.success("Gmail disconnected"); load();
  };
  const sendTest = async () => {
    if (!testTo.trim()) { toast.error("Enter a recipient email"); return; }
    try { await API.post("/admin/gmail/send-test", { to: testTo.trim() }); toast.success("Test email sent ✓"); }
    catch (e) { toast.error(apiErr(e)); }
  };

  const redirectUri = `${process.env.REACT_APP_BACKEND_URL}/api/oauth/gmail/callback`;

  if (!status) return <Spinner />;
  return (
    <div className="space-y-4" data-testid="email-tab">
      <div className="hivf-card p-4">
        <div className="flex items-center gap-2">
          <EnvelopeSimple size={20} weight="fill" className="text-[#EA4335]" />
          <h3 className="font-display text-sm font-extrabold text-slate-800">Email Sending — Gmail (Google OAuth)</h3>
          <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold ${status.connected ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>
            {status.connected ? "CONNECTED" : "NOT CONNECTED"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">Connect a Google account once. Lead emails & marketing email campaigns then send live via Gmail.</p>

        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#4A90E2]/5 p-3">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Add this exact Redirect URI in Google Cloud Console</span>
          <code className="flex-1 truncate rounded-lg bg-white px-2 py-1.5 text-[11px] text-slate-600" data-testid="gmail-redirect-uri">{redirectUri}</code>
          <button title="Copy" onClick={() => { navigator.clipboard.writeText(redirectUri); toast.success("Copied"); }} className="text-slate-400 hover:text-[#357ABD]"><Copy size={16} /></button>
        </div>

        {status.connected ? (
          <div className="mt-4">
            <p className="text-sm text-slate-700">Connected as <b>{status.email}</b></p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <div className="flex-1 min-w-[220px]">
                <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Send test email to</label>
                <input data-testid="gmail-test-to" className="hivf-input mt-1" placeholder="someone@example.com" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
              </div>
              <button onClick={sendTest} className="hivf-btn-primary !py-2" data-testid="gmail-send-test">Send test</button>
              {isAdmin && <button onClick={disconnect} className="hivf-btn-secondary !py-2" data-testid="gmail-disconnect">Disconnect</button>}
            </div>
          </div>
        ) : (
          isAdmin && (
            <button onClick={connect} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-700 shadow-sm hover:bg-slate-50" data-testid="gmail-connect">
              <GoogleLogo size={18} weight="bold" className="text-[#EA4335]" /> Connect Google account
            </button>
          )
        )}
      </div>
    </div>
  );
}

function WhatsAppTab({ isAdmin }) {
  const [cfg, setCfg] = useState(null);
  const [status, setStatus] = useState(null);
  const [phones, setPhones] = useState(null);
  const [templates, setTemplates] = useState(null);
  const [testTo, setTestTo] = useState("");
  const callbackUrl = `${process.env.REACT_APP_BACKEND_URL}/api/webhooks/whatsapp`;

  const load = () => {
    API.get("/admin/settings").then(({ data }) => setCfg(data.whatsapp_cloud || { graph_api_version: "v25.0" }));
    API.get("/admin/whatsapp/status").then(({ data }) => setStatus(data));
  };
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e?.preventDefault();
    try {
      await API.patch("/admin/settings", {
        key: "whatsapp_cloud",
        value: {
          access_token: (cfg.access_token || "").trim(), waba_id: (cfg.waba_id || "").trim(),
          app_id: (cfg.app_id || "").trim(),
          phone_number_id: (cfg.phone_number_id || "").trim(), app_secret: (cfg.app_secret || "").trim(),
          verify_token: (cfg.verify_token || "").trim(), graph_api_version: (cfg.graph_api_version || "v25.0").trim(),
        },
      });
      toast.success("WhatsApp settings saved"); load();
    } catch (err) { toast.error(apiErr(err)); }
  };

  const fetchPhones = async () => {
    try { const { data } = await API.post("/admin/whatsapp/phone-numbers"); setPhones(data.data || []); }
    catch (err) { toast.error(apiErr(err)); }
  };
  const fetchTemplates = async () => {
    try { const { data } = await API.post("/admin/whatsapp/templates"); setTemplates(data.data || []); }
    catch (err) { toast.error(apiErr(err)); }
  };
  const sendTest = async () => {
    if (!testTo.trim()) { toast.error("Enter a number (with country code)"); return; }
    try { await API.post("/admin/whatsapp/send-test", { to: testTo.trim() }); toast.success("Test message sent ✓"); }
    catch (err) { toast.error(apiErr(err)); }
  };
  const syncOdooTemplates = async () => {
    try {
      const { data } = await API.post("/admin/whatsapp/sync-odoo-templates");
      toast.success(`Linked ${data.linked_updated} approved templates from Odoo (${data.created} new)`);
    } catch (err) { toast.error(apiErr(err)); }
  };

  if (!cfg) return <Spinner />;
  return (
    <div className="space-y-4" data-testid="whatsapp-tab">
      <div className="hivf-card p-4">
        <div className="flex items-center gap-2">
          <WhatsappLogo size={20} weight="fill" className="text-[#25D366]" />
          <h3 className="font-display text-sm font-extrabold text-slate-800">WhatsApp Business Cloud API</h3>
          {status && <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold ${status.configured ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>{status.configured ? "CONNECTED" : "NOT CONNECTED"}</span>}
        </div>
        <p className="mt-1 text-xs text-slate-500">Send template & session messages live and receive inbound replies. Connect your Meta WhatsApp account, then paste the callback URL into Meta → WhatsApp → Configuration → Webhook.</p>

        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#25D366]/5 p-3">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Webhook Callback URL</span>
          <code className="flex-1 truncate rounded-lg bg-white px-2 py-1.5 text-[11px] text-slate-600" data-testid="wa-callback-url">{callbackUrl}</code>
          <button title="Copy" onClick={() => { navigator.clipboard.writeText(callbackUrl); toast.success("Copied"); }} className="text-slate-400 hover:text-[#25D366]"><Copy size={16} /></button>
        </div>

        <form onSubmit={save} className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {[["access_token", "System User Access Token", "password"], ["waba_id", "WhatsApp Business Account ID", "text"],
            ["app_id", "App ID", "text"],
            ["phone_number_id", "Phone Number ID", "text"], ["app_secret", "App Secret", "password"],
            ["verify_token", "Verify Token (you choose)", "text"], ["graph_api_version", "Graph API Version", "text"]].map(([k, label, type]) => (
            <div key={k}>
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</label>
              <input data-testid={`wa-${k}-input`} type={type} disabled={!isAdmin} className="hivf-input mt-1"
                value={cfg[k] || ""} onChange={(e) => setCfg((c) => ({ ...c, [k]: e.target.value }))} />
            </div>
          ))}
          {isAdmin && (
            <div className="flex flex-wrap items-end gap-2 md:col-span-2">
              <button data-testid="wa-save-button" type="submit" className="hivf-btn-primary !py-2"><WhatsappLogo size={14} /> Save Settings</button>
              <button type="button" onClick={fetchPhones} className="hivf-btn-secondary !py-2" data-testid="wa-fetch-phones">Fetch phone numbers</button>
              <button type="button" onClick={fetchTemplates} className="hivf-btn-secondary !py-2" data-testid="wa-fetch-templates">Fetch templates</button>
              <button type="button" onClick={syncOdooTemplates} className="hivf-btn-secondary !py-2" data-testid="wa-sync-odoo-templates">Sync approved templates from Odoo</button>
            </div>
          )}
        </form>

        {phones && (
          <div className="mt-3 rounded-xl bg-slate-50 p-3" data-testid="wa-phones-list">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Phone numbers</p>
            {phones.length === 0 && <p className="text-xs text-slate-400">None returned.</p>}
            {phones.map((p) => (
              <div key={p.id} className="mt-1 flex items-center gap-2 text-sm">
                <span className="font-semibold text-slate-700">{p.display_phone_number}</span>
                <code className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500">{p.id}</code>
                {isAdmin && <button onClick={() => setCfg((c) => ({ ...c, phone_number_id: p.id }))} className="text-xs font-bold text-[#357ABD]">Use</button>}
              </div>
            ))}
          </div>
        )}
        {templates && (
          <div className="mt-3 rounded-xl bg-slate-50 p-3" data-testid="wa-templates-list">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Approved templates</p>
            {templates.length === 0 && <p className="text-xs text-slate-400">None returned.</p>}
            <div className="mt-1 flex flex-wrap gap-1.5">
              {templates.map((t) => (
                <span key={t.name} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${t.status === "APPROVED" ? "bg-emerald-50 text-emerald-600" : "bg-slate-200 text-slate-500"}`}>{t.name} · {t.language}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="hivf-card p-4">
        <h3 className="font-display text-sm font-extrabold text-slate-800">Send a test message</h3>
        <p className="mt-1 text-xs text-slate-500">Sends a session text to a number that has messaged your business in the last 24h.</p>
        <div className="mt-3 flex gap-2">
          <input data-testid="wa-test-to" className="hivf-input" placeholder="Recipient number e.g. 919812345678" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
          <button onClick={sendTest} className="hivf-btn-primary" data-testid="wa-send-test">Send</button>
        </div>
      </div>
    </div>
  );
}

function MigrationTab() {
  const [status, setStatus] = useState(null);
  const [audit, setAudit] = useState(null);
  const [auditing, setAuditing] = useState(false);
  const [sync, setSync] = useState(null);
  const [confirmSync, setConfirmSync] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [lastDone, setLastDone] = useState(null);

  const load = () => API.get("/admin/migration/status").then(({ data }) => setStatus(data));
  const loadSync = () => API.get("/admin/sync/status").then(({ data }) => {
    setSync(data);
    if (data.running) setActiveRun(data.running);
  });
  useEffect(() => {
    load();
    loadSync();
    API.get("/admin/settings").then(({ data }) => data.last_audit && setAudit(data.last_audit));
  }, []);

  // poll active run
  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    const t = setInterval(async () => {
      const { data } = await API.get(`/admin/sync/runs/${activeRun.run_id}`);
      setActiveRun(data);
      if (data.status !== "running") {
        clearInterval(t);
        if (data.status === "done") {
          setLastDone(data);
          toast.success("Sync complete");
        } else {
          toast.error("Sync failed — see details below");
        }
        load();
        loadSync();
      }
    }, 3000);
    return () => clearInterval(t);
  }, [activeRun?.run_id, activeRun?.status]);

  const startSync = async () => {
    setConfirmSync(false);
    try {
      const { data } = await API.post("/admin/sync/start");
      setActiveRun({ run_id: data.run_id, status: "running", since: data.since, until: data.until, progress: {} });
      toast.info(`Sync started — fetching changes since ${data.since} UTC`);
    } catch (e) {
      toast.error(apiErr(e));
    }
  };

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
  const fmtUtc = (s) => (s ? new Date(s.replace(" ", "T") + "Z").toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " IST" : "—");
  const sumNew = (p) => Object.values(p || {}).reduce((a, v) => a + (v.new || 0), 0);
  const sumUpd = (p) => Object.values(p || {}).reduce((a, v) => a + (v.updated || 0), 0);

  return (
    <div className="space-y-4">
      {/* SYNC CARD */}
      <div className="hivf-card p-4" data-testid="sync-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-sm font-extrabold text-slate-800">Odoo Sync</h3>
            <p className="text-xs text-slate-500">Pull everything new/changed in Odoo into this CRM — keep both in lockstep until cutover.</p>
          </div>
          <button data-testid="sync-now-button" onClick={() => setConfirmSync(true)}
            disabled={activeRun?.status === "running"} className="hivf-btn-primary !py-1.5 text-xs">
            {activeRun?.status === "running" ? "Sync in progress…" : "Sync Now"}
          </button>
        </div>
        {sync && (
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="sync-info">
            <div className="rounded-xl bg-slate-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Last lead activity in CRM</p>
              <p className="mt-1 text-sm font-bold text-slate-700" data-testid="last-record-date">{fmtUtc(sync.last_record?.leads_write_date)}</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Last chatter message</p>
              <p className="mt-1 text-sm font-bold text-slate-700">{fmtUtc(sync.last_record?.lead_messages_date)}</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Last sync run</p>
              <p className="mt-1 text-sm font-bold text-slate-700" data-testid="last-sync-date">
                {sync.last_sync ? fmtUtc(sync.last_sync.finished_at) : "Never (initial migration only)"}
              </p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Next sync covers</p>
              <p className="mt-1 text-sm font-bold text-[#357ABD]">{sync.next_since ? `${fmtUtc(sync.next_since)} → now` : "FULL import (empty database)"}</p>
            </div>
          </div>
        )}

        {/* live progress */}
        {activeRun && (
          <div className={`mt-3 rounded-xl border p-3 ${activeRun.status === "running" ? "border-amber-200 bg-amber-50/50" : activeRun.status === "done" ? "border-emerald-200 bg-emerald-50/50" : "border-rose-200 bg-rose-50/50"}`} data-testid="sync-progress">
            <p className="text-xs font-bold text-slate-700">
              {activeRun.status === "running" ? `⏳ Syncing… (window: ${activeRun.since} → ${activeRun.until} UTC)` :
                activeRun.status === "done" ? `✅ Sync #${activeRun.run_id} complete — ${sumNew(activeRun.results || activeRun.progress)} new, ${sumUpd(activeRun.results || activeRun.progress)} updated` :
                `❌ Sync failed: ${(activeRun.error || "").slice(0, 200)}`}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(activeRun.results || activeRun.progress || {}).map(([k, v]) => (
                <span key={k} className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600">
                  {k.replace(/_/g, " ")}: <b className="text-emerald-600">+{v.new}</b>{v.updated ? <span className="text-[#357ABD]"> / {v.updated} upd</span> : ""}
                </span>
              ))}
            </div>
            {activeRun.status === "done" && activeRun.totals && (
              <p className="mt-2 text-[11px] text-slate-500">
                New totals — {Object.entries(activeRun.totals).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v.toLocaleString("en-IN")}`).join(" · ")}
              </p>
            )}
          </div>
        )}
        {!activeRun && sync?.last_sync && (
          <p className="mt-2 text-[11px] text-slate-400" data-testid="last-sync-summary">
            Last sync ({fmtUtc(sync.last_sync.finished_at)}): {sumNew(sync.last_sync.results)} new, {sumUpd(sync.last_sync.results)} updated · window {sync.last_sync.since} → {sync.last_sync.until} UTC
          </p>
        )}
      </div>

      {/* confirm modal */}
      {confirmSync && sync && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setConfirmSync(false)}>
          <div onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" data-testid="sync-confirm-modal">
            <h3 className="font-display text-lg font-extrabold text-slate-900">Confirm Odoo Sync</h3>
            <div className="mt-3 rounded-xl bg-[#4A90E2]/5 p-3 text-sm text-slate-700">
              {sync.next_since ? (
                <>I will fetch all records <b>created or updated in Odoo</b> between<br />
                  <b className="text-[#357ABD]">{sync.next_since} UTC</b> ({fmtUtc(sync.next_since)})<br />
                  and <b className="text-[#357ABD]">now</b>.</>
              ) : (
                <>This database is empty — I will run a <b>FULL import</b> of all Odoo data (leads, chatter, WhatsApp, contacts…). This can take 30–60 minutes.</>
              )}
            </div>
            <ul className="mt-3 space-y-1 text-xs text-slate-500">
              <li>• New Odoo records are added; changed records are updated.</li>
              <li>• For migrated leads edited in BOTH systems, Odoo values win.</li>
              <li>• Leads created directly in this CRM are never touched.</li>
              <li>• Dashboards & reports reflect new data immediately after.</li>
            </ul>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setConfirmSync(false)} className="hivf-btn-secondary" data-testid="sync-cancel-button">Cancel</button>
              <button onClick={startSync} className="hivf-btn-primary" data-testid="sync-confirm-button">Yes, Sync Now</button>
            </div>
          </div>
        </div>
      )}

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
