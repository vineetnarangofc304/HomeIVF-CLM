import axios from "axios";

export const API = axios.create({
  baseURL: `${process.env.REACT_APP_BACKEND_URL}/api`,
  withCredentials: true,
});

const TOKEN_KEY = "hivf_token";
export const setToken = (t) => { if (t) localStorage.setItem(TOKEN_KEY, t); };
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Attach a Bearer token fallback so auth works even when a browser blocks
// the cross-site httpOnly cookie (Safari ITP, strict 3rd-party cookie modes).
// ---- Global in-flight GET registry ----
// Under production load, slow reads saturate the browser's ~6 connections-per-host, so switching
// tabs makes the whole app "hang" behind the previous page's pending requests. On every route
// change we abort the previous route's pending GETs (see abortPendingReads) to instantly free
// those connection slots and cancel the matching server-side queries. Writes (POST/PATCH/DELETE)
// are NEVER auto-aborted, so an in-flight save always completes.
const _pendingGets = new Set();

export function abortPendingReads() {
  const cur = typeof window !== "undefined" ? window.location.pathname : null;
  _pendingGets.forEach((c) => {
    if (c.__path && c.__path !== cur) {
      try { c.abort(); } catch (_) {}
      _pendingGets.delete(c);
    }
  });
}

// Attach a Bearer token fallback + register a cancel signal for GETs (tagged with the route that
// issued them, so a later route change only cancels the OLD route's reads, never the new page's).
API.interceptors.request.use((config) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) config.headers.Authorization = `Bearer ${t}`;
  const method = (config.method || "get").toLowerCase();
  if (method === "get" && !config.signal) {
    const ctrl = new AbortController();
    ctrl.__path = typeof window !== "undefined" ? window.location.pathname : "";
    config.signal = ctrl.signal;
    config.__ctrl = ctrl;
    _pendingGets.add(ctrl);
  }
  return config;
});

let refreshing = null;
const TRANSIENT_STATUS = [502, 520, 521, 522, 523, 524, 525];
const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const _cleanup = (cfg) => { if (cfg && cfg.__ctrl) _pendingGets.delete(cfg.__ctrl); };

API.interceptors.response.use(
  (res) => { _cleanup(res.config); return res; },
  async (error) => {
    const original = error.config || {};
    _cleanup(original);

    // Request was cancelled because the user navigated away (RouteChangeAborter) and the owning
    // component is unmounting. Return a promise that NEVER settles: this globally suppresses the
    // CanceledError so it can't become an unhandled rejection (React's dev error overlay) or a
    // stray toast on ANY page — without needing a .catch on every route-mounted API.get.
    if (axios.isCancel(error) || error.code === "ERR_CANCELED") {
      return new Promise(() => {});
    }

    // 401 → refresh the session once, then replay the request.
    if (error.response?.status === 401 && !original._retry && !original.url?.includes("/auth/")) {
      original._retry = true;
      try {
        refreshing = refreshing || API.post("/auth/refresh").then((r) => {
          if (r.data?.access_token) setToken(r.data.access_token);
          return r;
        });
        await refreshing;
        refreshing = null;
        return API(original);
      } catch (e) {
        refreshing = null;
        clearToken();
        window.location.href = "/login";
      }
    }

    // Transient ORIGIN/connection errors — a busy origin momentarily returns an empty/malformed
    // response (Cloudflare 520/522), resets the connection, or a network blip occurs. This is what
    // users hit when switching tabs while the server is under load. Silently retry idempotent GETs
    // a couple of times with backoff so they see a brief spinner instead of a scary error. We do
    // NOT retry 503/504 (the app's own "overloaded/slow" fail-fast) so we never amplify DB load.
    const method = (original.method || "get").toLowerCase();
    const status = error.response?.status;
    const isTransient = (!error.response) || TRANSIENT_STATUS.includes(status);
    if (method === "get" && isTransient) {
      original._retryCount = (original._retryCount || 0) + 1;
      if (original._retryCount <= 2) {
        await _sleep(original._retryCount * 600);
        return API(original);
      }
    }

    return Promise.reject(error);
  }
);

export function apiErr(e) {
  if (axios.isCancel(e) || e?.code === "ERR_CANCELED") return "";
  const status = e?.response?.status;
  if (!e?.response || [502, 503, 504, 520, 521, 522, 523, 524, 525].includes(status)) {
    return "Server is busy right now — please try again in a moment.";
  }
  const d = e?.response?.data?.detail;
  if (!d) return e?.message || "Something went wrong";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  return d?.msg || String(d);
}

export function fmtDate(s) {
  if (!s) return "—";
  try {
    const d = new Date(s.includes("T") ? s : s.replace(" ", "T") + "Z");
    return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return s;
  }
}

export function fmtDay(s) {
  if (!s) return "—";
  try {
    const d = new Date(s.length > 10 ? (s.includes("T") ? s : s.replace(" ", "T") + "Z") : s + "T00:00:00");
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
  } catch {
    return s;
  }
}

export function todayStr() {
  const d = new Date(Date.now() + 5.5 * 3600 * 1000);
  return d.toISOString().slice(0, 10);
}

// Map a report dimension + raw key to /leads filter params (drill-down)
export function dimFilterParams(dim, key) {
  if (key === "__null__" || key == null || key === "__count__") {
    if (dim === "lead_stage") return { lead_stage: "__none__" };
    if (dim === "user_id") return { user_id: "none" };
    return {};
  }
  switch (dim) {
    case "user_id": return { user_id: key };
    case "tags": return { tags: key };
    case "lead_stage": return { lead_stage: key };
    case "stage_id": return { stage_id: key };
    case "source_lead": return { source_lead: key };
    case "follow_up_tag": return { follow_up_tag: key };
    case "ads_platform": return { ads_platform: key };
    case "campaign_name": return { campaign_name: key };
    case "city": return { city: key };
    case "state_name": return { state_name: key };
    case "priority": return { priority: key };
    case "lost_reason_id": return { lost_reason_id: key, active: "false" };
    case "create_date:day": return { date_from: key, date_to: key };
    case "create_date:month": return { date_from: `${key}-01`, date_to: `${key}-31` };
    default: return {};
  }
}

export function leadsUrl(params) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v != null && v !== "" && sp.set(k, v));
  return `/leads?${sp.toString()}`;
}
