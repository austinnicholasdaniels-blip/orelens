"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getScanner } from "@/lib/api";
import GradeChip from "@/components/GradeChip";

type Row = Record<string, any>;
const TABS = [
  { id: "active-drills", label: "Active Drill Programs" },
  { id: "high-grade-breakouts", label: "High-Grade Breakouts" },
  { id: "value-momentum", label: "Best Bang-for-Buck" },
] as const;

const COMMODITIES = ["Gold", "Silver", "Copper", "Nickel", "Lithium"];
const TIERS = ["Tier 1", "High Risk"];

const COLUMNS: Record<string, { key: string; label: string }[]> = {
  "active-drills": [
    { key: "ticker", label: "Ticker" }, { key: "project", label: "Project" },
    { key: "commodity", label: "Commodity" }, { key: "rigs_active", label: "Rigs" },
    { key: "planned_meters", label: "Planned m" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "grade", label: "Grade" },
  ],
  "high-grade-breakouts": [
    { key: "ticker", label: "Ticker" }, { key: "intercept", label: "Intercept" },
    { key: "grade_meters", label: "Gram-meters" }, { key: "volume_ratio", label: "Vol ×20d" },
    { key: "hit_pct", label: "Hit %" }, { key: "grade", label: "Grade" },
  ],
  "value-momentum": [
    { key: "ticker", label: "Ticker" }, { key: "score", label: "Score" },
    { key: "ev_per_oz", label: "EV/oz" }, { key: "factors", label: "Factors" },
    { key: "runway_m", label: "Runway (mo)" }, { key: "grade", label: "Grade" },
  ],
};

export default function Dashboard() {
  const [tab, setTab] = useState<string>(TABS[0].id);
  const [commodity, setCommodity] = useState("");
  const [tier, setTier] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "", dir: -1 });
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    const params: Record<string, string> = {};
    if (commodity) params.commodity = commodity;
    if (tier) params.tier = tier;
    try {
      setRows(await getScanner(tab, params));
    } catch {
      setError("Couldn't reach the API. Start the backend, then refresh.");
      setRows([]);
    }
  }, [tab, commodity, tier]);

  useEffect(() => { load(); }, [load]);

  const sorted = useMemo(() => {
    if (!sort.key) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key];
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av > bv ? 1 : av < bv ? -1 : 0) * sort.dir;
    });
  }, [rows, sort]);

  const cols = COLUMNS[tab];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-5">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`font-display text-lg tracking-wide px-4 py-1.5 rounded-sm border ${
              tab === t.id ? "border-assay text-assay bg-tray" : "border-seam text-ash hover:text-bone"}`}>
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex gap-2">
          <select value={commodity} onChange={(e) => setCommodity(e.target.value)}
            className="bg-tray border border-seam rounded-sm text-sm px-2 py-1.5">
            <option value="">All commodities</option>
            {COMMODITIES.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select value={tier} onChange={(e) => setTier(e.target.value)}
            className="bg-tray border border-seam rounded-sm text-sm px-2 py-1.5">
            <option value="">All jurisdictions</option>
            {TIERS.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {error && <p className="text-hazard text-sm mb-4">{error}</p>}

      <table className="core-tray w-full">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className="cursor-pointer select-none"
                onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : -1 }))}>
                {c.label}{sort.key === c.key ? (sort.dir === -1 ? " ↓" : " ↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.ticker}>
              {cols.map((c) => (
                <td key={c.key} className={c.key === "ticker" ? "font-mono" : ""}>
                  {c.key === "ticker" ? (
                    <a href={`/ticker/${r.ticker}`} className="text-assay hover:underline">
                      {r.ticker}<span className="text-ash text-xs">.{r.exchange}</span>
                    </a>
                  ) : c.key === "grade" ? (
                    <GradeChip grade={r.grade} />
                  ) : c.key === "factors" ? (
                    <span className="text-xs text-ash">{(r.factors ?? []).join(" · ")}</span>
                  ) : (
                    <span>{r[c.key] ?? "—"}</span>
                  )}
                </td>
              ))}
            </tr>
          ))}
          {!error && sorted.length === 0 && (
            <tr><td colSpan={cols.length} className="text-ash text-center py-8">
              No companies match these filters. Clear a filter or run the nightly sync.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
