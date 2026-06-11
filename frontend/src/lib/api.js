import axios from "axios";

export const API = axios.create({
  baseURL: `${process.env.REACT_APP_BACKEND_URL}/api`,
  withCredentials: true,
});

let refreshing = null;

API.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry && !original.url.includes("/auth/")) {
      original._retry = true;
      try {
        refreshing = refreshing || API.post("/auth/refresh");
        await refreshing;
        refreshing = null;
        return API(original);
      } catch (e) {
        refreshing = null;
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export function apiErr(e) {
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
