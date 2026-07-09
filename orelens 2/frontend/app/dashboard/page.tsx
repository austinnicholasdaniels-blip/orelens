"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getScanner } from "@/lib/api";
import GradeChip from "@/components/GradeChip";
import BetaGate from "@/components/BetaGate";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Row = Record<string, any>;
const TABS = [
  { id: "all-stocks", label: "All Stocks" },
  { id: "value-momentum", label: "Best Bang-for-Buck" },
  { id: "bullish-setups", label: "Bullish Setups" },
  { id: "dilution-risk", label: "Dilution Risk" },
  { id: "burn-league", label: "Burn League" },
  { id: "serial-raisers", label: "Serial Raisers" },
  { id: "most-dilutive", label: "Most Dilutive" },
  { id: "coiled-springs", label: "Coiled Springs" },
  { id: "unlock-calendar", label: "Unlock Calendar" },
  { id: "stock-promotions", label: "Stock Promotions" },
  { id: "active-drills", label: "Active Drill Programs" },
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
  "value-momentum": [
    { key: "ticker", label: "Ticker" }, { key: "score", label: "Score" },
    { key: "ev_per_oz", label: "EV/oz" }, { key: "factors", label: "Factors" },
    { key: "runway_m", label: "Runway (mo)" }, { key: "grade", label: "Grade" },
  ],
  "bullish-setups": [
    { key: "ticker", label: "Ticker" }, { key: "price", label: "Price" },
    { key: "score", label: "Score" }, { key: "ret_60d_pct", label: "60d %" },
    { key: "off_high_pct", label: "Off High %" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "why", label: "Setup" }, { key: "grade", label: "Grade" },
  ],
  "dilution-risk": [
    { key: "ticker", label: "Ticker" }, { key: "probability", label: "Raise Probability" },
    { key: "score", label: "Score" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "cash_m", label: "Cash ($M)" }, { key: "raises_3y", label: "Raises 3y" },
    { key: "why", label: "Signals" }, { key: "grade", label: "Grade" },
  ],
  "burn-league": [
    { key: "ticker", label: "Ticker" }, { key: "name", label: "Company" },
    { key: "monthly_burn", label: "Burn/mo ($)" }, { key: "cash_m", label: "Cash ($M)" },
    { key: "raised_since_m", label: "Raised Since ($M)" },
    { key: "runway_m", label: "Runway (mo)" }, { key: "as_of", label: "As Of" },
    { key: "grade", label: "Grade" },
  ],
  "serial-raisers": [
    { key: "ticker", label: "Ticker" }, { key: "raises_3y", label: "Raises 3y" },
    { key: "raises_per_year", label: "Per Year" }, { key: "last_raise", label: "Last Raise" },
    { key: "last_raise_pct", label: "Last Size %" }, { key: "shares_growth_pct", label: "Total Growth %" },
    { key: "grade", label: "Grade" },
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
    { key: "ticker", label: "Ticker" }, { key: "name", label: "Company" },
    { key: "amount", label: "Paid ($)" }, { key: "status", label: "Status" },
  ],
  "active-drills": [
    { key: "ticker", label: "Ticker" }, { key: "project", label: "Project" },
    { key: "signal", label: "Why Active" }, { key: "last_activity", label: "Last Activity" },
    { key: "rigs_active", label: "Rigs" }, { key: "runway_m", label: "Runway (mo)" },
    { key: "grade", label: "Grade" },
  ],
};

const DESCRIPTIONS: Record<string, string> = {
  "all-stocks": "Every company OreLens tracks, with the latest close and day-over-day move, sorted by the day's biggest gainers. Click any column header to re-sort, or any ticker for its full capital-structure profile.",
  "value-momentum": "Only companies holding an A or B dilution grade qualify. Scores stack cheap ounces (low EV per resource ounce), volatility contraction with drying volume during an active drill program, and open-market insider buying in the last 60 days - funded stories getting quieter while insiders step in.",
  "most-dilutive": "Ranks companies by the largest quarter-over-quarter percentage increase in shares outstanding, straight from quarterly filings. Shows exactly how many new shares hit the register and the total growth across the tracked window.",
  "coiled-springs": "Price within 15% of the 90-day high, 10-day average volume at least 1.3x the prior 50-day average, and a clean share structure (max 8% QoQ share growth, never grade D or F). Volume precedes price in illiquid juniors - this catches accumulation before the breakout. Rare by design.",
  "unlock-calendar": "Every detected private placement or bought deal that has closed, with the Canadian 4-month hold expiry computed automatically. The free-trading date is a supply event - the day placement paper can legally hit the market. Sorted soonest first; red means under two weeks out.",
  "active-drills": "A company qualifies on any of three signals: drill-start news within 150 days, a program flagged ongoing at any age, or drill results published within 150 days. The Why Active column shows which signal fired and the date of the latest activity.",
};

const EMPTY: Record<string, string> = {
  "bullish-setups": "No setups clearing the bar: uptrend, volume, runway, and clean structure all have to line up. These are rare on purpose.",
  "dilution-risk": "No elevated raise-probability names right now. Scores build from runway, cash trend, and issuance habits.",
  "burn-league": "Burn data loads from quarterly cash-flow statements - populates after the deep-history backfill.",
  "serial-raisers": "Needs multi-quarter share history - populates after the deep-history backfill.",
  "stock-promotions": "No disclosed investor-awareness or IR engagements found in the last 5 months. Run POST /api/admin/backfill-promotions to scan, or wait for the nightly wire sync.",
  "unlock-calendar": "No tracked financings approaching their 4-month hold expiry. This fills automatically as placement closings cross the wire.",
  "most-dilutive": "No companies with a quarter-over-quarter share increase in the tracked window.",
  "coiled-springs": "No coiled springs right now: nothing is holding near its 90-day high with building volume and a clean share structure. These setups are rare by design - when one appears, pay attention.",
  "active-drills": "No active drill programs detected: no drill-start news or published results in the last 5 months, and no programs flagged ongoing. Fills as the nightly news sync accumulates.",
};

export default function Dashboard() {
  return <BetaGate><DashboardInner /></BetaGate>;
}

function DashboardInner() {
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
      const data = await getScanner(tab, params);
      // one row per ticker on every scanner except News: event-based scanners
      // (financings, intercepts, promotions) can emit several rows for one
      // company; servers sort best/soonest first, so keeping the first is right
      if (tab === "news") {
        setRows(data);
      } else {
        const seen = new Set<string>();
        setRows(data.filter((r: Row) => {
          if (!r.ticker) return true;
          if (seen.has(r.ticker)) return false;
          seen.add(r.ticker);
          return true;
        }));
      }
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
          placeholder="Search any mining stock - TSX, TSXV, CSE, NYSE, NASDAQ, ASX..."
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

      {DESCRIPTIONS[tab] && (
        <p className="text-ash text-sm mb-4 max-w-4xl border-l-2 border-assay/60 pl-3">
          {DESCRIPTIONS[tab]}
        </p>
      )}

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
            <tr key={r.ticker ?? i}>
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
