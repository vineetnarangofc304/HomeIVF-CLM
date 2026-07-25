import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { API, setToken, clearToken } from "../lib/api";

const AuthContext = createContext(null);
const CatalogContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=guest, obj=logged in
  const [catalogs, setCatalogs] = useState(null);

  const loadCatalogs = useCallback(async () => {
    try {
      const { data } = await API.get("/catalogs");
      setCatalogs(data);
    } catch (e) {
      /* noop */
    }
  }, []);

  const didBootstrap = useRef(false);
  useEffect(() => {
    if (didBootstrap.current) return; // guard React StrictMode's dev double-invoke (fire /auth/me once)
    didBootstrap.current = true;
    (async () => {
      // GUARANTEED-BOUNDED bootstrap: race /auth/me against a hard 10s timer so a hung/stalled
      // response can NEVER leave the app frozen on a blank spinner. `noCancel` keeps this request
      // OUT of the route-abort registry — otherwise an axios timeout aborts via the signal and
      // surfaces as ERR_CANCELED, which the response interceptor swallows into a never-settling
      // promise that would deadlock the bootstrap. On any failure/timeout we fall back to the guest
      // state (login) rather than hang. setUser is intentionally NOT gated on an `alive` flag:
      // AuthProvider is the root (never really unmounts) and gating it broke under StrictMode (the
      // first pass's cleanup set alive=false while the guard skipped the second pass → result
      // discarded → permanent blank spinner).
      try {
        const { data } = await Promise.race([
          API.get("/auth/me", { noCancel: true }),
          new Promise((_, reject) => setTimeout(() => reject(new Error("auth-bootstrap-timeout")), 10000)),
        ]);
        setUser(data);
      } catch {
        setUser(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (user && user !== false) loadCatalogs();
  }, [user, loadCatalogs]);

  const login = async (email, password) => {
    const { data } = await API.post("/auth/login", { email, password });
    setToken(data.access_token);
    setUser(data);
    return data;
  };

  const logout = async () => {
    try {
      await API.post("/auth/logout");
    } finally {
      clearToken();
      setUser(false);
      setCatalogs(null);
    }
  };

  const can = useCallback(
    (perm) => !!(user && user !== false && (user.permissions || {})[perm]),
    [user]
  );

  return (
    <AuthContext.Provider value={{ user, login, logout, can }}>
      <CatalogContext.Provider value={{ catalogs, refreshCatalogs: loadCatalogs }}>
        {children}
      </CatalogContext.Provider>
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
export const useCatalogs = () => useContext(CatalogContext);

export function useCatalogMaps() {
  const { catalogs } = useCatalogs();
  if (!catalogs) return { tagById: {}, userById: {}, stageById: {}, lostById: {}, catalogs: null };
  const m = (arr) => Object.fromEntries((arr || []).map((x) => [x.id, x]));
  return {
    catalogs,
    tagById: m(catalogs.tag),
    userById: m(catalogs.users),
    stageById: m(catalogs.stage),
    lostById: m(catalogs.lost_reason),
  };
}
