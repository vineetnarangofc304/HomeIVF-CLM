import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
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

  useEffect(() => {
    let alive = true;
    (async () => {
      // Bootstrap the session WITHOUT freezing the whole app on a blank spinner: /auth/me now has
      // a bounded per-request timeout and we retry a single transient hiccup before falling back
      // to the guest state (login). A 401 (no/bad token) is a definite guest → stop immediately.
      for (let i = 0; i < 2; i++) {
        try {
          const { data } = await API.get("/auth/me", { timeout: 25000 });
          if (alive) setUser(data);
          return;
        } catch (e) {
          if (e?.response?.status === 401) break;
          if (i === 0) await new Promise((r) => setTimeout(r, 800));
        }
      }
      if (alive) setUser(false);
    })();
    return () => { alive = false; };
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
