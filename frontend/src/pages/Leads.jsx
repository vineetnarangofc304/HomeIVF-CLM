import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CaretLeft, CaretRight, FunnelSimple, Kanban, ListBullets, Plus, FloppyDisk, X, PhoneCall } from "@phosphor-icons/react";
import { API, apiErr, fmtDay, fmtDate } from "../lib/api";
import { useAuth, useCatalogMaps } from "../context/AuthContext";
import { TagChip, StageBadge, Spinner, EmptyState } from "../components/Bits";

const FILTER_DEFS = [
  { key: "lead_stage", label: "Lead Stage" },
  { key: "tags", label: "Disposition Tag" },
  { key: "user_id", label: "Caller" },
  { key: "source_lead", label: "Source" },
  { key: "follow_up", label: "Follow-up" },
  { key: "follow_up_tag", label: "FU Tag" },
  { key: "active", label: "Status" },
  { key: "date_from", label: "From" },
  { key: "date_to", label: "To" },
  { key: "campaign_name", label: "Campaign" },
  { key: "ads_platform", label: "Ads Platform" },
  { key: "state_name", label: "State" },
  { key: "city", label: "City" },
  { key: "lost_reason_id", label: "Lost Reason" },
];

const GROUP_OPTIONS = [
  ["", "No grouping"], ["user_id", "Caller"], ["tags", "Disposition Tag"], ["lead_stage", "Lead Stage"],
  ["source_lead", "Source"], ["follow_up_tag", "Follow-up Tag"], ["create_date:day", "Created Day"],
  ["create_date:month", "Created Month"], ["state_name", "State"], ["city", "City"],
  ["ads_platform", "Ads Platform"], ["campaign_name", "Campaign"],
];

export default function Leads() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { catalogs, tagById, userById } = useCatalogMaps();
  const [data, setData] = useState(null);
  const [groups, setGroups] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState([]);
  const [savedFilters, setSavedFilters] = useState([]);
  const [showCreate, setShowCreate] = useState(false);

  const view = params.get("view") || "list";
  const groupBy = params.get("group_by") || "";
  const page = parseInt(params.get("page") || "1");

  const filterParams = useMemo(() => {
    const obj = {};
    ["search", "lead_stage", "tags", "user_id", "source_lead", "follow_up", "active", "date_from", "date_to",
      "stage_id", "follow_up_tag", "campaign_name", "ads_platform", "state_name", "city", "lost_reason_id"].forEach((k) => {
      const v = params.get(k);
      if (v) obj[k] = v;
    });
    return obj;
  }, [params]);

  const sort = params.get("sort") || "create_date";
  const order = params.get("order") || "desc";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (view === "kanban") {
        const { data } = await API.get("/leads/group_counts", { params: { ...filterParams, group_by: "lead_stage" } });
        const cols = {};
        await Promise.all(
          data.map(async (g) => {
            const key = g.key || "__none__";
            const { data: list } = await API.get("/leads", {
              params: { ...filterParams, lead_stage: g.key || "__none__", limit: 15 },
            });
            cols[key] = { count: g.count, items: list.items, label: g.key || "Undefined" };
          })
        );
        setGroups(cols);
        setData(null);
      } else if (groupBy) {
        const { data } = await API.get("/leads/group_counts", { params: { ...filterParams, group_by: groupBy } });
        setGroups(data);
        setData(null);
      } else {
        const { data } = await API.get("/leads", { params: { ...filterParams, page, limit: 50, sort, order } });
        setData(data);
        setGroups(null);
      }
      setSelected([]);
    } catch (e) {
      toast.error(apiErr(e));
    } finally {
      setLoading(false);
    }
  }, [filterParams, page, view, groupBy, sort, order]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    API.get("/filters", { params: { page: "leads" } }).then(({ data }) => setSavedFilters(data)).catch(() => {});
  }, []);

  const setParam = (k, v) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    next.delete("page");
    setParams(next);
  };

  const groupLabel = (key) => {
    if (key === null || key === false || key === "") return "Undefined";
    if (groupBy === "user_id") return userById[key]?.name || key;
    if (groupBy === "tags") return tagById[key]?.name || key;
    return String(key);
  };

  const applyGroupFilter = (key) => {
    const next = new URLSearchParams(params);
    next.delete("group_by");
    const map = { "create_date:day": ["date_from", "date_to"], "create_date:month": null };
    if (groupBy === "create_date:day") { next.set("date_from", key); next.set("date_to", key); }
    else if (groupBy === "create_date:month") { next.set("date_from", key + "-01"); next.set("date_to", key + "-31"); }
    else if (key === null || key === false || key === "") { /* skip */ }
    else next.set(groupBy === "tags" ? "tags" : groupBy, String(key));
    setParams(next);
  };

  const saveCurrentFilter = async () => {
    const name = window.prompt("Name this filter:");
    if (!name) return;
    try {
      const { data } = await API.post("/filters", { name, page: "leads", params: { ...filterParams }, group_by: groupBy || null });
      setSavedFilters((s) => [...s, data]);
      toast.success("Filter saved");
    } catch (e) { toast.error(apiErr(e)); }
  };

  const applySaved = (f) => {
    const next = new URLSearchParams();
    Object.entries(f.params || {}).forEach(([k, v]) => v && next.set(k, v));
    if (f.group_by) next.set("group_by", f.group_by);
    setParams(next);
  };

  const bulk = async (action, payload = {}) => {
    try {
      await API.post("/leads/bulk", { ids: selected, action, payload });
      toast.success(`Done: ${action} on ${selected.length} leads`);
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  const pushToDialer = async () => {
    if (!window.confirm(`Push ${selected.length} lead(s) into the Ozonetel auto-dialer (Autocallback_homeivf)? The dialer will start calling them.`)) return;
    try {
      const { data } = await API.post("/calls/push-to-dialer", { lead_ids: selected });
      toast.success(`Auto-dialer → ${data.queued} queued${data.failed ? `, ${data.failed} failed` : ""}${data.skipped ? `, ${data.skipped} skipped (no phone)` : ""}`);
      load();
    } catch (e) { toast.error(apiErr(e)); }
  };

  const activeChips = FILTER_DEFS.filter((f) => params.get(f.key));

  const toggleSort = (field) => {
    const next = new URLSearchParams(params);
    if (sort === field) next.set("order", order === "desc" ? "asc" : "desc");
    else { next.set("sort", field); next.set("order", "desc"); }
    next.delete("page");
    setParams(next);
  };

  const Th = ({ field, children }) => (
    <th className={`px-2 py-2.5 ${field ? "cursor-pointer select-none hover:text-[#357ABD]" : ""}`}
      onClick={field ? () => toggleSort(field) : undefined} data-testid={field ? `sort-${field}` : undefined}>
      {children}{field && sort === field && <span className="ml-0.5">{order === "desc" ? "▾" : "▴"}</span>}
    </th>
  );

  const totalPages = data ? Math.max(1, Math.ceil(data.total / 50)) : 1;

  return (
    <div className="flex h-full flex-col" data-testid="leads-page">
      {/* Toolbar */}
      <div className="border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="mr-2 font-display text-lg font-extrabold text-slate-900">Leads</h1>
          <input
            data-testid="leads-search-input"
            defaultValue={params.get("search") || ""}
            key={params.get("search") || ""}
            onKeyDown={(e) => e.key === "Enter" && setParam("search", e.target.value)}
            placeholder="Search name / phone / email…"
            className="hivf-input !w-60"
          />
          <select data-testid="filter-lead-stage" className="hivf-select" value={params.get("lead_stage") || ""} onChange={(e) => setParam("lead_stage", e.target.value)}>
            <option value="">Lead Stage: All</option>
            {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <select data-testid="filter-tag" className="hivf-select max-w-44" value={params.get("tags") || ""} onChange={(e) => setParam("tags", e.target.value)}>
            <option value="">Tag: All</option>
            {(catalogs?.tag || []).filter((t) => t.active !== false).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          {user.role !== "caller" && (
            <select data-testid="filter-caller" className="hivf-select max-w-40" value={params.get("user_id") || ""} onChange={(e) => setParam("user_id", e.target.value)}>
              <option value="">Caller: All</option>
              <option value="none">Unassigned</option>
              {(catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          )}
          <select data-testid="filter-source" className="hivf-select" value={params.get("source_lead") || ""} onChange={(e) => setParam("source_lead", e.target.value)}>
            <option value="">Source: All</option>
            {(catalogs?.source_lead || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <select data-testid="filter-followup" className="hivf-select" value={params.get("follow_up") || ""} onChange={(e) => setParam("follow_up", e.target.value)}>
            <option value="">Follow-up: Any</option>
            <option value="today">Due Today</option>
            <option value="overdue">Overdue</option>
            <option value="upcoming">Upcoming</option>
            <option value="set">Has follow-up</option>
          </select>
          <select data-testid="filter-followup-tag" className="hivf-select" value={params.get("follow_up_tag") || ""} onChange={(e) => setParam("follow_up_tag", e.target.value)}>
            <option value="">FU Tag: All</option>
            {(catalogs?.follow_up_tag || []).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
          </select>
          <select data-testid="filter-active" className="hivf-select" value={params.get("active") || "true"} onChange={(e) => setParam("active", e.target.value)}>
            <option value="true">Active</option>
            <option value="false">Lost / Archived</option>
            <option value="all">All</option>
          </select>
          <input data-testid="filter-date-from" type="date" className="hivf-select" value={params.get("date_from") || ""} onChange={(e) => setParam("date_from", e.target.value)} />
          <input data-testid="filter-date-to" type="date" className="hivf-select" value={params.get("date_to") || ""} onChange={(e) => setParam("date_to", e.target.value)} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <FunnelSimple size={15} className="text-slate-400" />
          <select data-testid="group-by-select" className="hivf-select" value={groupBy} onChange={(e) => setParam("group_by", e.target.value)}>
            {GROUP_OPTIONS.map(([v, l]) => <option key={v} value={v}>{v ? `Group by: ${l}` : l}</option>)}
          </select>
          <div className="flex overflow-hidden rounded-lg border border-slate-200">
            <button data-testid="view-list-button" onClick={() => setParam("view", "")} className={`px-2.5 py-1.5 ${view === "list" ? "bg-[#4A90E2]/10 text-[#357ABD]" : "bg-white text-slate-500"}`}><ListBullets size={16} /></button>
            <button data-testid="view-kanban-button" onClick={() => setParam("view", "kanban")} className={`px-2.5 py-1.5 ${view === "kanban" ? "bg-[#4A90E2]/10 text-[#357ABD]" : "bg-white text-slate-500"}`}><Kanban size={16} /></button>
          </div>
          <button data-testid="save-filter-button" onClick={saveCurrentFilter} className="hivf-btn-secondary !px-3 !py-1.5 text-xs"><FloppyDisk size={14} /> Save filter</button>
          {savedFilters.length > 0 && (
            <select data-testid="saved-filters-select" className="hivf-select" value="" onChange={(e) => { const f = savedFilters.find((x) => x.id === parseInt(e.target.value)); if (f) applySaved(f); }}>
              <option value="">Saved filters…</option>
              {savedFilters.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          )}
          {activeChips.map((f) => (
            <span key={f.key} className="inline-flex items-center gap-1 rounded-full bg-[#4A90E2]/10 px-2.5 py-1 text-[11px] font-semibold text-[#357ABD]">
              {f.label}: {f.key === "user_id" ? (userById[params.get(f.key)]?.name || params.get(f.key)) : f.key === "tags" ? (tagById[params.get(f.key)]?.name || params.get(f.key)) : params.get(f.key)}
              <button onClick={() => setParam(f.key, "")}><X size={11} /></button>
            </span>
          ))}
          <div className="flex-1" />
          <button data-testid="new-lead-button" onClick={() => setShowCreate(true)} className="hivf-btn-primary !px-3 !py-1.5 text-xs"><Plus size={14} /> New Lead</button>
        </div>
      </div>

      {/* Bulk bar */}
      {selected.length > 0 && user.role !== "caller" && (
        <div className="flex items-center gap-2 border-b border-amber-100 bg-amber-50 px-5 py-2 text-sm" data-testid="bulk-action-bar">
          <span className="font-bold text-amber-700">{selected.length} selected</span>
          <select className="hivf-select" data-testid="bulk-assign-select" value="" onChange={(e) => e.target.value && bulk("assign", { user_id: e.target.value })}>
            <option value="">Assign to…</option>
            {(catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <select className="hivf-select" data-testid="bulk-tag-select" value="" onChange={(e) => e.target.value && bulk("add_tags", { tags: [e.target.value] })}>
            <option value="">Add tag…</option>
            {(catalogs?.tag || []).filter((t) => t.active !== false).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select className="hivf-select" data-testid="bulk-stage-select" value="" onChange={(e) => e.target.value && bulk("set_lead_stage", { lead_stage: e.target.value })}>
            <option value="">Set lead stage…</option>
            {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <button className="hivf-btn-secondary !py-1 text-xs" data-testid="bulk-archive-button" onClick={() => bulk("archive")}>Archive</button>
          <button className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-1 text-xs font-bold text-white hover:bg-indigo-600" data-testid="bulk-push-dialer-button" onClick={pushToDialer}><PhoneCall size={14} weight="bold" /> Push to Dialer</button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {loading ? <Spinner /> : view === "kanban" ? (
          <KanbanView groups={groups} userById={userById} tagById={tagById} />
        ) : groupBy && groups ? (
          <div className="p-5">
            <table className="w-full max-w-2xl text-sm" data-testid="grouped-table">
              <thead><tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-2">{GROUP_OPTIONS.find(([v]) => v === groupBy)?.[1]}</th><th className="py-2 text-right">Leads</th></tr></thead>
              <tbody>
                {groups.map((g, i) => (
                  <tr key={i} onClick={() => applyGroupFilter(g.key)} className="cursor-pointer border-b border-slate-100 transition-colors hover:bg-[#4A90E2]/5">
                    <td className="py-2 font-semibold text-slate-700">{groupLabel(g.key)}</td>
                    <td className="py-2 text-right font-bold text-slate-600">{g.count.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : data?.items?.length ? (
          <table className="w-full text-sm" data-testid="leads-table">
            <thead className="sticky top-0 z-10 bg-slate-50">
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
                <th className="px-3 py-2.5">
                  <input type="checkbox" data-testid="select-all-checkbox"
                    checked={selected.length === data.items.length && data.items.length > 0}
                    onChange={(e) => setSelected(e.target.checked ? data.items.map((l) => l.id) : [])} />
                </th>
                <Th field="contact_name">Lead</Th>
                <Th field="phone">Phone</Th>
                <Th field="city">Location</Th>
                <Th field="user_id">Caller</Th>
                <Th field="lead_stage">Lead Stage</Th>
                <Th>Tags</Th>
                <Th field="follow_up_date">Follow-up</Th>
                <Th field="source_lead">Source</Th>
                <Th field="create_date">Created</Th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id} data-testid={`lead-row-${l.id}`} onClick={() => navigate(`/leads/${l.id}`)}
                  className="cursor-pointer border-b border-slate-100 bg-white transition-colors hover:bg-[#4A90E2]/5">
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.includes(l.id)}
                      onChange={(e) => setSelected((s) => e.target.checked ? [...s, l.id] : s.filter((x) => x !== l.id))} />
                  </td>
                  <td className="px-2 py-2">
                    <p className="font-semibold text-slate-800">{l.contact_name || l.name}</p>
                    <div className="flex items-center gap-1">
                      {!l.active && <span className="text-[10px] font-bold uppercase text-rose-500">Lost</span>}
                      {l.is_duplicate && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold uppercase text-amber-700" data-testid={`lead-dup-${l.id}`} title={`Duplicate of #${l.duplicate_of}`}>Dup</span>}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-slate-600">{l.phone || "—"}</td>
                  <td className="px-2 py-2 text-slate-500">{[l.city, l.state_name].filter(Boolean).join(", ") || "—"}</td>
                  <td className="px-2 py-2 text-slate-600">{userById[l.user_id]?.name || <span className="text-slate-300">Unassigned</span>}</td>
                  <td className="px-2 py-2"><StageBadge stage={l.lead_stage} /></td>
                  <td className="px-2 py-2">
                    <div className="flex max-w-52 flex-wrap gap-1">
                      {(l.tags || []).slice(0, 3).map((t) => <TagChip key={t} tag={tagById[t]} />)}
                      {(l.tags || []).length > 3 && <span className="text-[10px] text-slate-400">+{l.tags.length - 3}</span>}
                    </div>
                  </td>
                  <td className="px-2 py-2 text-slate-600">
                    {l.follow_up_date ? (
                      <span className={l.follow_up_date < new Date(Date.now() + 5.5 * 3600000).toISOString().slice(0, 10) ? "font-bold text-rose-500" : ""}>
                        {fmtDay(l.follow_up_date)}{l.follow_up_tag ? ` · ${l.follow_up_tag.replace("Follow UP", "FU")}` : ""}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-2 py-2 text-slate-500">{l.source_lead || "—"}</td>
                  <td className="px-2 py-2 text-slate-500">{fmtDate(l.create_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No leads found" subtitle="Try adjusting your filters" />
        )}
      </div>

      {/* Pagination */}
      {!groupBy && view === "list" && data && (
        <div className="flex items-center justify-between border-t border-slate-200 bg-white px-5 py-2.5 text-sm">
          <span className="text-slate-500" data-testid="leads-total-count">
            {data.total.toLocaleString("en-IN")} leads · page {page} of {totalPages.toLocaleString("en-IN")}
          </span>
          <div className="flex gap-2">
            <button data-testid="prev-page-button" disabled={page <= 1} onClick={() => setParams((p) => { const n = new URLSearchParams(p); n.set("page", page - 1); return n; })} className="hivf-btn-secondary !p-2 disabled:opacity-40"><CaretLeft size={14} /></button>
            <button data-testid="next-page-button" disabled={page >= totalPages} onClick={() => setParams((p) => { const n = new URLSearchParams(p); n.set("page", page + 1); return n; })} className="hivf-btn-secondary !p-2 disabled:opacity-40"><CaretRight size={14} /></button>
          </div>
        </div>
      )}

      {showCreate && <CreateLeadModal onClose={() => setShowCreate(false)} onCreated={(l) => { setShowCreate(false); navigate(`/leads/${l.id}`); }} catalogs={catalogs} />}
    </div>
  );
}

function KanbanView({ groups, userById, tagById }) {
  const navigate = useNavigate();
  if (!groups) return null;
  const order = ["Contact Attempt", "Contacted", "Converted", "Closed", "__none__"];
  const keys = Object.keys(groups).sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  return (
    <div className="flex h-full gap-4 overflow-x-auto p-5" data-testid="kanban-view">
      {keys.map((k) => (
        <div key={k} className="flex w-72 shrink-0 flex-col rounded-2xl bg-slate-100/60 p-3">
          <div className="mb-3 flex items-center justify-between px-1">
            <StageBadge stage={groups[k].label} />
            <span className="text-xs font-bold text-slate-500">{groups[k].count.toLocaleString("en-IN")}</span>
          </div>
          <div className="space-y-2 overflow-y-auto">
            {groups[k].items.map((l) => (
              <div key={l.id} onClick={() => navigate(`/leads/${l.id}`)}
                className="cursor-pointer rounded-xl border border-slate-200 bg-white p-3 transition-all hover:-translate-y-[2px] hover:shadow-md">
                <p className="text-sm font-bold text-slate-800">{l.contact_name || l.name}</p>
                <p className="text-xs text-slate-500">{l.phone}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">{(l.tags || []).slice(0, 2).map((t) => <TagChip key={t} tag={tagById[t]} />)}</div>
                <p className="mt-1.5 text-[11px] text-slate-400">{userById[l.user_id]?.name || "Unassigned"} · {fmtDay(l.create_date?.slice(0, 10))}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CreateLeadModal({ onClose, onCreated, catalogs }) {
  const [form, setForm] = useState({ contact_name: "", phone: "", email_from: "", city: "", state_name: "", source_lead: "", lead_stage: "", user_id: "", query: "" });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = Object.fromEntries(Object.entries(form).filter(([, v]) => v));
      if (payload.user_id) payload.user_id = parseInt(payload.user_id);
      const { data } = await API.post("/leads", payload);
      toast.success("Lead created");
      onCreated(data);
    } catch (err) {
      toast.error(apiErr(err));
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl" data-testid="create-lead-modal">
        <h3 className="font-display text-lg font-extrabold text-slate-900">New Lead</h3>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <input data-testid="create-lead-name" required placeholder="Contact name *" className="hivf-input" value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} />
          <input data-testid="create-lead-phone" required placeholder="Phone *" className="hivf-input" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
          <input placeholder="Email" className="hivf-input" value={form.email_from} onChange={(e) => set("email_from", e.target.value)} />
          <input placeholder="City" className="hivf-input" value={form.city} onChange={(e) => set("city", e.target.value)} />
          <input placeholder="State" className="hivf-input" value={form.state_name} onChange={(e) => set("state_name", e.target.value)} />
          <select className="hivf-select" value={form.source_lead} onChange={(e) => set("source_lead", e.target.value)}>
            <option value="">Source…</option>
            {(catalogs?.source_lead || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <select className="hivf-select" value={form.lead_stage} onChange={(e) => set("lead_stage", e.target.value)}>
            <option value="">Lead stage…</option>
            {(catalogs?.lead_stage || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
          </select>
          <select className="hivf-select" value={form.user_id} onChange={(e) => set("user_id", e.target.value)}>
            <option value="">Assign caller…</option>
            {(catalogs?.users || []).filter((u) => u.active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <textarea placeholder="Query / notes" className="hivf-input col-span-2" rows={2} value={form.query} onChange={(e) => set("query", e.target.value)} />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="hivf-btn-secondary">Cancel</button>
          <button data-testid="create-lead-submit" type="submit" disabled={saving} className="hivf-btn-primary">{saving ? "Creating…" : "Create Lead"}</button>
        </div>
      </form>
    </div>
  );
}
