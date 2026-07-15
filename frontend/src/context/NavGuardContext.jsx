import React, { createContext, useContext, useRef, useState, useCallback } from "react";
import { Warning, X } from "@phosphor-icons/react";

const NavGuardContext = createContext(null);

// A global guard that lets a page (LeadDetail) block navigation until mandatory
// fields are filled. The page registers a checker fn that returns the list of
// missing field labels (or null/[] when it's fine to leave). Every navigation
// entry-point (sidebar, search, logout, in-page buttons, browser back/refresh)
// asks this guard first and shows a blocking popup listing what's missing.
export function NavGuardProvider({ children }) {
  const guardRef = useRef(null); // () => string[] | null
  const [missing, setMissing] = useState(null);

  const registerGuard = useCallback((fn) => { guardRef.current = fn; }, []);
  const clearGuard = useCallback(() => { guardRef.current = null; }, []);

  // Silent check — no UI (used by beforeunload where the browser shows its own dialog).
  const isBlocked = useCallback(() => {
    const m = guardRef.current ? guardRef.current() : null;
    return !!(m && m.length);
  }, []);

  // Returns true if navigation is allowed; false + shows popup when blocked.
  const checkAllowed = useCallback(() => {
    const m = guardRef.current ? guardRef.current() : null;
    if (m && m.length) { setMissing(m); return false; }
    return true;
  }, []);

  const closePopup = useCallback(() => setMissing(null), []);

  return (
    <NavGuardContext.Provider value={{ registerGuard, clearGuard, isBlocked, checkAllowed }}>
      {children}
      {missing && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 p-4" data-testid="mandatory-fields-modal">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2 text-rose-600">
                <Warning size={22} weight="fill" />
                <h3 className="font-display text-lg font-extrabold text-slate-900">Complete mandatory fields</h3>
              </div>
              <button onClick={closePopup} data-testid="mandatory-fields-close" className="rounded-full p-1 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
            </div>
            <p className="mt-2 text-sm text-slate-600">
              You can't leave this lead until these mandatory fields are filled:
            </p>
            <ul className="mt-3 space-y-1.5" data-testid="mandatory-fields-list">
              {missing.map((f) => (
                <li key={f} className="flex items-center gap-2 rounded-lg bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-rose-500" /> {f}
                </li>
              ))}
            </ul>
            <button onClick={closePopup} data-testid="mandatory-fields-ok"
              className="mt-5 w-full rounded-full bg-[#4A90E2] py-2.5 text-sm font-bold text-white transition-colors hover:bg-[#357ABD]">
              Stay & fill fields
            </button>
          </div>
        </div>
      )}
    </NavGuardContext.Provider>
  );
}

export function useNavGuard() {
  return useContext(NavGuardContext) || { registerGuard: () => {}, clearGuard: () => {}, isBlocked: () => false, checkAllowed: () => true };
}
