"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getScanner } from "@/lib/api";
import GradeChip from "@/components/GradeChip";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Row = Record<string, any>;
const TABS = [
  { id: "all-stocks", label: "All Stocks" },
  { id: "news", label: "News" },
  { id: "value-momentum", label: "Best Bang-for-Buck" },
  { id: "most-dilutive", label: "Most Dilutive" },
  { id: "coiled-springs", label: "Coiled Springs" },
  { id: "unlock-calendar", label: "Unlock Calendar" },
  { id: "stock-promotions", label: "Stock Promotions" },
  { id: "active-drills", label: "Active Drill Programs" },
  { id: "high-grade-breakouts", label: "High-Grade Breakouts" },
] as const;

const COMMODITIES = ["Gold", "Silver", "Copper", "Nickel", "Lithium"];
const TIERS = ["Tier 1", "High Risk"];

const COLUMNS: Record<string, { key: string; label: string }[]> = {
  "all-stocks": [
    { key: "ticker", label: "Ticker" }, { key: "name", label: "Company" },
    { key: "price", label: "Price" }, { key: "change_pct", label: "Day %" },
    { key: "volume", label: "Volume" }, { key: "commodity", label: "Commodity" },
    { key: "grade", label: "Grade" },
  ],
  "news": [
    { key: "published", label: "Published" }, { key: "ticker", label: "Ticker" },
    { key: "headline", label: "Headline" }, { key: "wire", label: "Wire" },
  ],
  "value-momentum": [
    { key: "ticker", label: "Ticker" }, { key: "score", label: "Score" },
    { key: "ev_per_oz", label: "EV/oz" }, { key: "factors", label: "Factors" },
    { key: "runway_m", label: "Runway (mo)" }, { key: "grade", label: "Grade" },
  ],
  "most-dilutive": [
    { key: "ticker", label: "Ticker" }, { key: "qoq_pct", label: "Shares Added QoQ %" },
    { key: "shares_added_m", label: "New Shares (M)" }, { key: "total_growth_pct", label: "Total Growth %" },
    { key: "as_of", label: "As Of Quarter" }, { key: "grade", label: "Grade" },
  ],
  "coiled-springs": [
    { key: "ticker", label: "Ticker" }, { key: "price", label: "Price" },
    { key: "off_high_pct", label: "Off 90d High %" }, { key: "vol_surge_x", label: "Vol Surge x" },
    { key: "ret_20d_pct", label: "20d Return %" }, { key: "qoq_dilution_pct", label: "QoQ Dilution %" },
    { key: "score", label: "Score" }, { key: "grade", label: "Grade" },
  ],
  "unlock-calendar": [
    { key: "ticker", label: "Ticker" }, { key: "kind", label: "Type" },
    { key: "amount_m", label: "Raise ($M)" }, { key: "price", label: "Unit Price" },
    { key: "est_shares_m", label: "Est. Shares (M)" }, { key: "warrant_strike", label: "Wt Strike" },
    { key: "hold_expiry", label: "Free-Trading Date" }, { key: "days_until", label: "Days Until" },
  ],
  "stock-promotions": [
    { key: "ticker", label: "Ticker" }, { key: "firm", label: "Promotion Firm" },
    { key: "amount", label: "Total ($)" }, { key: "monthly_fee", label: "Monthly ($)" },
    { key: "term_months", label: "Term (mo)" }, { key: "announced", label: "Announced" },
    { key: "ends", label: "Ends" }, { key: "status", label: "Status" },
  ],
  "active-drills": [
    { key: "ticker", label: "Ticker" }, { key: "project", label: "Project" },
    { key: "signal", label: "Why Active" }, { key: "last_activity", label: "Last Activity" },
    { key: "rigs_active", label: "Rigs" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "grade", label: "Grade" },
  ],
  "high-grade-breakouts": [
    { key: "ticker", label: "Ticker" }, { key: "intercept", label: "Intercept" },
    { key: "grade_meters", label: "Gram-meters" }, { key: "volume_ratio", label: "Vol x20d" },
    { key: "hit_pct", label: "Hit %" }, { key: "grade", label: "Grade" },
  ],
};

const EMPTY: Record<string, string> = {
  "stock-promotions": "No disclosed investor-awareness or IR engagements found in the last 5 months. Run POST /api/admin/backfill-promotions to scan, or wait for the nightly wire sync.",
  "unlock-calendar": "No tracked financings approaching their 4-month hold expiry. This fills automatically as placement closings cross the wire.",
  "news": "No press releases collected yet today. The wire sync runs nightly at 11 PM ET - or trigger it any time via POST /api/jobs/nightly.",
  "most-dilutive": "No companies with a quarter-over-quarter share increase in the tracked window.",
  "coiled-springs": "No coiled springs right now: nothing is holding near its 90-day high with building volume and a clean share structure. These setups are rare by design - when one appears, pay attention.",
  "active-drills": "No active drill programs detected: no drill-start news or published results in the last 5 months, and no programs flagged ongoing. Fills as the nightly news sync accumulates.",
  "high-grade-breakouts": "No benchmark-beating intercepts with volume breakouts recently. These are rare by design.",
};

export default function Dashboard() {
  const [tab, setTab] = useState<string>("all-stocks");
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
    setRows([]);   // clear immediately so one tab's rows never flash under another tab's columns
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
                onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : (["days_until", "hold_expiry", "last_activity"].includes(c.key) ? 1 : -1) }))}>
                {c.label}{sort.key === c.key ? (sort.dir === -1 ? " v" : " ^") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={(r.ticker ?? "") + i}>
              {cols.map((c) => (
                <td key={c.key} className={c.key === "ticker" ? "font-mono" : ""}>
                  {c.key === "ticker" ? (
                    r.ticker ? (
                      <a href={`/ticker/${r.ticker}`} className="text-assay hover:underline">
                        {r.ticker}<span className="text-ash text-xs">.{r.exchange}</span>
                      </a>
                    ) : (<span className="text-ash">-</span>)
                  ) : c.key === "change_pct" ? (
                    <span className={r.change_pct == null ? "text-ash" : r.change_pct >= 0 ? "text-oxide" : "text-hazard"}>
                      {r.change_pct == null ? "-" : (r.change_pct > 0 ? "+" : "") + r.change_pct + "%"}
                    </span>
                  ) : c.key === "status" ? (
                    <span className={String(r.status ?? "").startsWith("ACTIVE") ? "text-hazard font-semibold" : "text-ash"}>
                      {r.status}
                    </span>
                  ) : c.key === "amount" || c.key === "monthly_fee" ? (
                    <span className="font-mono">{r[c.key] != null ? "$" + Number(r[c.key]).toLocaleString() : "-"}</span>
                  ) : c.key === "days_until" ? (
                    <span className={r.days_until <= 14 ? "text-hazard font-semibold" : r.days_until <= 45 ? "text-assay" : ""}>
                      {r.days_until}
                    </span>
                  ) : c.key === "headline" ? (
                    <a href={r.url} target="_blank" rel="noopener noreferrer" className="hover:text-assay hover:underline">
                      {r.headline}{r.drill_start ? " \u26cf" : ""}
                    </a>
                  ) : c.key === "published" ? (
                    <span className="text-xs text-ash font-mono">{(r.published ?? "").slice(0, 16).replace("T", " ")}</span>
                  ) : c.key === "volume" ? (
                    <span className="font-mono">{(r.volume ?? 0).toLocaleString()}</span>
                  ) : c.key === "grade" ? (
                    <GradeChip grade={r.grade} />
                  ) : c.key === "why" ? (
                    <span className="text-xs text-ash">{r.why}</span>
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
