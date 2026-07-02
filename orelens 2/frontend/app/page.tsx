"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getScanner } from "@/lib/api";
import GradeChip from "@/components/GradeChip";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Row = Record<string, any>;
const TABS = [
  { id: "value-momentum", label: "Best Bang-for-Buck" },
  { id: "active-drills", label: "Active Drill Programs" },
  { id: "high-grade-breakouts", label: "High-Grade Breakouts" },
] as const;

const COMMODITIES = ["Gold", "Silver", "Copper", "Nickel", "Lithium"];
const TIERS = ["Tier 1", "High Risk"];

const COLUMNS: Record<string, { key: string; label: string }[]> = {
  "value-momentum": [
    { key: "ticker", label: "Ticker" }, { key: "score", label: "Score" },
    { key: "ev_per_oz", label: "EV/oz" }, { key: "factors", label: "Factors" },
    { key: "runway_m", label: "Runway (mo)" }, { key: "grade", label: "Grade" },
  ],
  "active-drills": [
    { key: "ticker", label: "Ticker" }, { key: "project", label: "Project" },
    { key: "commodity", label: "Commodity" }, { key: "rigs_active", label: "Rigs" },
    { key: "planned_meters", label: "Planned m" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "grade", label: "Grade" },
  ],
  "high-grade-breakouts": [
    { key: "ticker", label: "Ticker" }, { key: "intercept", label: "Intercept" },
    { key: "grade_meters", label: "Gram-meters" }, { key: "volume_ratio", label: "Vol x20d" },
    { key: "hit_pct", label: "Hit %" }, { key: "grade", label: "Grade" },
  ],
};

const EMPTY: Record<string, string> = {
  "active-drills": "No companies with drill-start news in the last 45 days. This fills as the nightly news sync runs.",
  "high-grade-breakouts": "No benchmark-beating intercepts with volume breakouts recently. These are rare by design.",
};

export default function Dashboard() {
  const [tab, setTab] = useState<string>("value-momentum");
  const [commodity, setCommodity] = useState("");
  const [tier, setTier] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "", dir: -1 });
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Row[]>([]);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setError("");
    const params: Record<string, string> = {};
    if (commodity) params.commodity = commodity;
    if (tier) params.tier = tier;
    try {
      setRows(await getScanner(tab, params));
    } catch {
      setError("Couldn't reach the API. It may be waking up - retry in ~30s.");
      setRows([]);
    }
  }, [tab, commodity, tier]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
        setHits(await r.json());
      } catch { setHits([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const addTicker = async () => {
    setAdding(true);
    try {
      const r = await fetch(`${API}/api/admin/add-ticker`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: q.trim().toUpperCase() }),
      });
      const d = await r.json();
      if (d.added) window.location.href = `/ticker/${d.added}`;
      else alert(d.error || "Could not add ticker");
    } catch { alert("Could not reach the API"); }
    setAdding(false);
  };

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
      <div className="relative mb-5">
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search any junior mining stock - ticker or name..."
          className="w-full bg-tray border border-seam rounded-sm px-4 py-2.5 text-sm placeholder:text-ash focus:border-assay focus:outline-none" />
        {q.trim().length >= 2 && (
          <div className="absolute z-10 mt-1 w-full bg-tray border border-seam rounded-sm shadow-lg">
            {hits.map((h) => (
              <a key={h.ticker} href={`/ticker/${h.ticker}`}
                 className="flex items-baseline gap-3 px-4 py-2 hover:bg-shale text-sm">
                <span className="font-mono text-assay">{h.ticker}</span>
                <span>{h.name}</span>
                <span className="text-ash text-xs ml-auto">{h.exchange} - {h.commodity}</span>
              </a>
            ))}
            {hits.length === 0 && (
              <button onClick={addTicker} disabled={adding}
                className="w-full text-left px-4 py-2 text-sm hover:bg-shale">
                {adding ? "Fetching market data..." :
                  `Not tracked yet - add "${q.trim().toUpperCase()}" and pull its data now`}
              </button>
            )}
          </div>
        )}
      </div>

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
                {c.label}{sort.key === c.key ? (sort.dir === -1 ? " v" : " ^") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={r.ticker ?? i}>
              {cols.map((c) => (
                <td key={c.key} className={c.key === "ticker" ? "font-mono" : ""}>
                  {c.key === "ticker" ? (
                    <a href={`/ticker/${r.ticker}`} className="text-assay hover:underline">
                      {r.ticker}<span className="text-ash text-xs">.{r.exchange}</span>
                    </a>
                  ) : c.key === "grade" ? (
                    <GradeChip grade={r.grade} />
                  ) : c.key === "factors" ? (
                    <span className="text-xs text-ash">{(r.factors ?? []).join(" - ")}</span>
                  ) : (
                    <span>{r[c.key] ?? "-"}</span>
                  )}
                </td>
              ))}
            </tr>
          ))}
          {!error && sorted.length === 0 && (
            <tr><td colSpan={cols.length} className="text-ash text-center py-8">
              {EMPTY[tab] ?? "No companies match these filters."}
            </td></tr>
          )}
        </tbody>
      </table>

    </div>
  );
}
