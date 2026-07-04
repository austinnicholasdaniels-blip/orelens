type Q = { as_of: string; cash: number; change_pct: number | null };

export default function CashHistoryChart({ history }: { history: Q[] }) {
  if (!history?.length) return null;
  const max = Math.max(...history.map((h) => h.cash));
  return (
    <div className="bg-tray border border-seam rounded-sm p-4">
      <h3 className="text-ash text-xs tracking-widest uppercase mb-3">
        Cash Balance by Quarter
      </h3>
      <div className="space-y-2">
        {history.map((h) => (
          <div key={h.as_of} className="flex items-center gap-3 text-sm">
            <span className="text-ash font-mono w-20 shrink-0">{h.as_of.slice(0, 7)}</span>
            <div className="flex-1 bg-shale rounded-sm h-4 overflow-hidden">
              <div className="h-4 bg-oxide/70"
                   style={{ width: `${max ? (h.cash / max) * 100 : 0}%` }} />
            </div>
            <span className="font-mono w-20 text-right shrink-0">
              ${(h.cash / 1e6).toFixed(1)}M
            </span>
            <span className={`w-24 text-right text-xs shrink-0 ${
              h.change_pct == null ? "text-ash" :
              h.change_pct < 0 ? "text-hazard" : "text-oxide"}`}>
              {h.change_pct == null ? "\u2014" :
               (h.change_pct > 0 ? "+" : "") + h.change_pct + "% QoQ"}
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-ash mt-3">
        Red = treasury shrinking that quarter (burn). Source: quarterly balance sheets.
      </p>
    </div>
  );
}

