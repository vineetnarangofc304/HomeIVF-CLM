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
