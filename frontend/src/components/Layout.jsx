import React, { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  SquaresFour, UsersThree, ClockCountdown, WhatsappLogo, ChartBar,
  EnvelopeSimple, GearSix, SignOut, MagnifyingGlass, Sparkle, PhoneCall, Megaphone, Gauge,
} from "@phosphor-icons/react";
import { useAuth } from "../context/AuthContext";
import { useNavGuard } from "../context/NavGuardContext";
import IncomingCallBanner from "./IncomingCallBanner";
import WaNotifier from "./WaNotifier";
import FollowUpReminder from "./FollowUpReminder";
import AgentStatusSwitcher from "./AgentStatusSwitcher";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: SquaresFour, testid: "nav-dashboard", perm: "dashboard" },
  { to: "/leads", label: "Leads", icon: UsersThree, testid: "nav-leads", perm: "leads" },
  { to: "/followups", label: "Follow-ups", icon: ClockCountdown, testid: "nav-followups", perm: "followups" },
  { to: "/call-center", label: "Call Center", icon: PhoneCall, testid: "nav-call-center", perm: "call_center" },
  { to: "/whatsapp", label: "WhatsApp", icon: WhatsappLogo, testid: "nav-whatsapp", perm: "whatsapp" },
  { to: "/marketing", label: "Marketing", icon: Megaphone, testid: "nav-marketing", perm: "marketing" },
  { to: "/reports", label: "Reports", icon: ChartBar, testid: "nav-reports", perm: "reports" },
  { to: "/kpi", label: "KPI Report", icon: Gauge, testid: "nav-kpi", perm: "reports" },
  { to: "/ai-insights", label: "AI Insights", icon: Sparkle, testid: "nav-ai-insights", perm: "reports" },
  { to: "/templates", label: "Templates", icon: EnvelopeSimple, testid: "nav-templates", perm: "templates" },
];

export default function Layout({ children }) {
  const { user, logout, can } = useAuth();
  const { checkAllowed } = useNavGuard();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  // Block any navigation away while a page (LeadDetail) reports missing mandatory fields.
  const guardClick = (e) => { if (!checkAllowed()) e.preventDefault(); };

  const onSearch = (e) => {
    e.preventDefault();
    if (!checkAllowed()) return;
    if (search.trim()) navigate(`/leads?search=${encodeURIComponent(search.trim())}`);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="px-5 py-5">
          <img src="/brand/homeivf-logo.svg" alt="HomeIVF" className="h-10" />
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.25em] text-[#8B5CF6]">CRM</p>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.filter(({ perm }) => can(perm)).map(({ to, label, icon: Icon, testid }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={guardClick}
              data-testid={testid}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors ${
                  isActive ? "bg-[#4A90E2]/10 text-[#357ABD]" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              <Icon size={19} weight="duotone" />
              {label}
            </NavLink>
          ))}
          {(can("admin")) && (
            <NavLink
              to="/admin"
              onClick={guardClick}
              data-testid="nav-admin"
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors ${
                  isActive ? "bg-[#4A90E2]/10 text-[#357ABD]" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              <GearSix size={19} weight="duotone" />
              Admin
            </NavLink>
          )}
        </nav>
        <NavLink to="/ai-insights" onClick={guardClick} data-testid="nav-ai-brain-card" className="mx-3 mb-3 block rounded-xl bg-gradient-to-br from-[#8B5CF6]/10 to-[#4A90E2]/10 p-3 transition hover:from-[#8B5CF6]/20 hover:to-[#4A90E2]/20">
          <div className="flex items-center gap-2 text-[#8B5CF6]">
            <Sparkle size={16} weight="fill" />
            <span className="text-xs font-bold">AI Brain</span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">Ask questions & explore live insights on all your data →</p>
        </NavLink>
        <div className="border-t border-slate-100 px-5 py-3">
          <p className="text-[10px] uppercase tracking-[0.2em] text-slate-400">Powered by TifTech</p>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-5">
          <form onSubmit={onSearch} className="relative w-full max-w-md">
            <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              data-testid="global-search-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search leads by name, phone, email…"
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-4 text-sm focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#4A90E2]/40"
            />
          </form>
          <div className="flex items-center gap-3">
            <AgentStatusSwitcher />
            <div className="text-right">
              <p className="text-sm font-bold text-slate-800" data-testid="topbar-user-name">{user.name}</p>
              <p className="text-[11px] capitalize text-slate-500">{user.role}</p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#4A90E2]/15 font-display text-sm font-extrabold text-[#357ABD]">
              {user.name?.[0]?.toUpperCase()}
            </div>
            <button data-testid="logout-button" onClick={() => { if (checkAllowed()) logout(); }} title="Logout"
              className="rounded-full p-2 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500">
              <SignOut size={18} />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
      {/* The incoming-call screen-pop polls /calls/active every 8s. That endpoint is user-scoped to
          Ozonetel-mapped agents, so for admins/managers who never receive assigned calls it always
          returns null — pure wasted load. Only mount it for users who can actually take a call. */}
      {(user.role === "caller" || user.ozonetel_agent_id) && <IncomingCallBanner />}
      <WaNotifier />
      <FollowUpReminder />
    </div>
  );
}
