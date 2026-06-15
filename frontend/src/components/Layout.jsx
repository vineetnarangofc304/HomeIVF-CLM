import React, { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  SquaresFour, UsersThree, ClockCountdown, WhatsappLogo, ChartBar,
  EnvelopeSimple, GearSix, SignOut, MagnifyingGlass, Sparkle,
} from "@phosphor-icons/react";
import { useAuth } from "../context/AuthContext";
import IncomingCallBanner from "./IncomingCallBanner";

const NAV = [
  { to: "/", label: "Dashboard", icon: SquaresFour, testid: "nav-dashboard" },
  { to: "/leads", label: "Leads", icon: UsersThree, testid: "nav-leads" },
  { to: "/followups", label: "Follow-ups", icon: ClockCountdown, testid: "nav-followups" },
  { to: "/whatsapp", label: "WhatsApp", icon: WhatsappLogo, testid: "nav-whatsapp" },
  { to: "/reports", label: "Reports", icon: ChartBar, testid: "nav-reports" },
  { to: "/templates", label: "Templates", icon: EnvelopeSimple, testid: "nav-templates" },
];

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  const onSearch = (e) => {
    e.preventDefault();
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
          {NAV.map(({ to, label, icon: Icon, testid }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
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
          {(user.role === "admin" || user.role === "manager") && (
            <NavLink
              to="/admin"
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
        <div className="mx-3 mb-3 rounded-xl bg-gradient-to-br from-[#8B5CF6]/10 to-[#4A90E2]/10 p-3">
          <div className="flex items-center gap-2 text-[#8B5CF6]">
            <Sparkle size={16} weight="fill" />
            <span className="text-xs font-bold">AI Brain</span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">Coming in Phase 2 — conversational insights on all your data.</p>
        </div>
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
            <div className="text-right">
              <p className="text-sm font-bold text-slate-800" data-testid="topbar-user-name">{user.name}</p>
              <p className="text-[11px] capitalize text-slate-500">{user.role}</p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#4A90E2]/15 font-display text-sm font-extrabold text-[#357ABD]">
              {user.name?.[0]?.toUpperCase()}
            </div>
            <button data-testid="logout-button" onClick={logout} title="Logout"
              className="rounded-full p-2 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500">
              <SignOut size={18} />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
      <IncomingCallBanner />
    </div>
  );
}
