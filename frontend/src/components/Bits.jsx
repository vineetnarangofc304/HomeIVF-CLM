import React from "react";

// tag color index -> tailwind tints
const TAG_COLORS = [
  "bg-slate-100 text-slate-700", "bg-rose-50 text-rose-700", "bg-orange-50 text-orange-700",
  "bg-amber-50 text-amber-700", "bg-cyan-50 text-cyan-700", "bg-purple-50 text-purple-700",
  "bg-pink-50 text-pink-700", "bg-teal-50 text-teal-700", "bg-blue-50 text-blue-700",
  "bg-fuchsia-50 text-fuchsia-700", "bg-emerald-50 text-emerald-700", "bg-violet-50 text-violet-700",
];

export function TagChip({ tag, onRemove }) {
  if (!tag) return null;
  const cls = TAG_COLORS[(tag.color || 0) % TAG_COLORS.length];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {tag.name}
      {onRemove && (
        <button onClick={onRemove} className="text-current opacity-60 hover:opacity-100" data-testid={`remove-tag-${tag.id}`}>
          ×
        </button>
      )}
    </span>
  );
}

const STAGE_STYLE = {
  "Contact Attempt": "bg-amber-50 text-amber-700 border-amber-200",
  Contacted: "bg-blue-50 text-blue-700 border-blue-200",
  Converted: "bg-emerald-50 text-emerald-700 border-emerald-200",
  Closed: "bg-slate-100 text-slate-600 border-slate-200",
};

export function StageBadge({ stage }) {
  if (!stage) return <span className="text-xs text-slate-400">—</span>;
  const cls = STAGE_STYLE[stage] || "bg-violet-50 text-violet-700 border-violet-200";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{stage}</span>;
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="h-7 w-7 animate-spin rounded-full border-2 border-[#4A90E2] border-t-transparent" />
    </div>
  );
}

export function EmptyState({ title, subtitle }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <p className="font-display text-base font-bold text-slate-700">{title}</p>
      {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
    </div>
  );
}
