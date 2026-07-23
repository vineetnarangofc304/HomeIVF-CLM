import React, { useEffect, useState } from "react";
import { CaretDown } from "@phosphor-icons/react";
import { API } from "../lib/api";

const STATUSES = ["Available", "On Call", "Lunch Break", "Washroom Break", "Refreshment Break", "Meeting", "Offline"];
const DOT = {
  "Available": "bg-emerald-500", "On Call": "bg-indigo-500",
  "Lunch Break": "bg-amber-500", "Washroom Break": "bg-amber-500",
  "Refreshment Break": "bg-amber-500", "Meeting": "bg-sky-500", "Offline": "bg-slate-400",
};

export default function AgentStatusSwitcher() {
  const [status, setStatus] = useState("Offline");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const load = () => API.get("/agent/me").then(({ data }) => setStatus(data.status || "Offline")).catch(() => {});
    load();
    // Poll so an admin-forced status change (e.g. forced Offline) reflects here promptly.
    const t = setInterval(load, 45000);
    return () => clearInterval(t);
  }, []);

  const change = async (s) => {
    setOpen(false);
    const prev = status;
    setStatus(s);
    try { await API.post("/agent/status", { status: s }); } catch { setStatus(prev); }
  };

  return (
    <div className="relative" data-testid="agent-status-switcher">
      <button onClick={() => setOpen((o) => !o)} data-testid="agent-status-button"
        className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:border-[#4A90E2]">
        <span className={`h-2.5 w-2.5 rounded-full ${DOT[status] || "bg-slate-400"}`} />
        {status}
        <CaretDown size={12} className="text-slate-400" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-1 w-48 rounded-xl border border-slate-200 bg-white p-1 shadow-xl" data-testid="agent-status-menu">
            {STATUSES.map((s) => (
              <button key={s} onClick={() => change(s)} data-testid={`agent-status-option-${s.replace(/\s+/g, "-").toLowerCase()}`}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-semibold hover:bg-slate-50 ${s === status ? "text-[#357ABD]" : "text-slate-600"}`}>
                <span className={`h-2.5 w-2.5 rounded-full ${DOT[s]}`} /> {s}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
