// Case 5 — WhatsApp message lifecycle statuses (shared across tracking pages)
export const WA_STATUS_FLOW = [
  "in_queue", "sent", "delivered", "read", "replied", "received", "failed", "bounced", "cancelled",
];

export const WA_STATUS_META = {
  in_queue: { label: "In Queue", cls: "bg-slate-100 text-slate-500", dot: "#94a3b8" },
  sent: { label: "Sent", cls: "bg-sky-50 text-sky-600", dot: "#0ea5e9" },
  delivered: { label: "Delivered", cls: "bg-indigo-50 text-indigo-600", dot: "#6366f1" },
  read: { label: "Read", cls: "bg-emerald-50 text-emerald-600", dot: "#10b981" },
  replied: { label: "Replied", cls: "bg-teal-50 text-teal-600", dot: "#14b8a6" },
  received: { label: "Received", cls: "bg-teal-50 text-teal-600", dot: "#14b8a6" },
  failed: { label: "Failed", cls: "bg-rose-50 text-rose-600", dot: "#f43f5e" },
  bounced: { label: "Bounced", cls: "bg-rose-50 text-rose-600", dot: "#f43f5e" },
  cancelled: { label: "Cancelled", cls: "bg-slate-100 text-slate-400", dot: "#cbd5e1" },
};

export const waMeta = (s) => WA_STATUS_META[s] || { label: s || "—", cls: "bg-slate-100 text-slate-500", dot: "#94a3b8" };
