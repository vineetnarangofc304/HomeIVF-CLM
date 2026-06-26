import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { API } from "../lib/api";

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
    API.get("/auth/me")
      .then(({ data }) => setUser(data))
      .catch(() => setUser(false));
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

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
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
