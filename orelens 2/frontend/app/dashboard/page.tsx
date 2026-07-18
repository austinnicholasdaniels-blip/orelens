// build: add-flow-v2
// build: sidebar-v2
"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getScanner } from "@/lib/api";
import GradeChip from "@/components/GradeChip";
import BetaGate from "@/components/BetaGate";
import WatchlistBar from "@/components/WatchlistBar";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Row = Record<string, any>;
const BULLISH_TABS = [
  { id: "value-momentum", label: "Best Bang-for-Buck" },
  { id: "bullish-setups", label: "Bullish Setups" },
  { id: "coiled-springs", label: "Coiled Springs" },
  { id: "active-drills", label: "Active Drill Programs" },
] as const;

const RISK_TABS = [
  { id: "dilution-risk", label: "Dilution Risk" },
  { id: "burn-league", label: "Burn League" },
  { id: "serial-raisers", label: "Serial Raisers" },
  { id: "most-dilutive", label: "Most Dilutive" },
  { id: "unlock-calendar", label: "Unlock Calendar" },
  { id: "stock-promotions", label: "Stock Promotions" },
] as const;

const TABS = [
  { id: "all-stocks", label: "All Stocks" },
  ...BULLISH_TABS,
  ...RISK_TABS,
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
  const [spot, setSpot] = useState<Row | null>(null);

  useEffect(() => {
    fetch(`${API}/api/spotlight`).then((r) => r.json())
      .then((s) => s?.active && setSpot(s)).catch(() => {});
  }, []);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "", dir: -1 });
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Row[]>([]);
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState("");

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

  const ADD_STEPS = [
    "Locating the listing\u2026",
    "Pulling 5 years of prices\u2026",
    "Reading shares outstanding & cash\u2026",
    "Grading the balance sheet\u2026",
  ];

  const addTicker = async () => {
    const tick = q.trim().toUpperCase();
    setAdding(true);
    setAddMsg(ADD_STEPS[0]);
    try {
      const r = await fetch(`${API}/api/request-ticker`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: tick }),
      });
      const d = await r.json();
      if (d.tracked) { window.location.href = `/ticker/${d.ticker}`; return; }
      if (d.error) { alert(d.error); setAdding(false); return; }
      // background pull started - poll for up to ~2 minutes
      for (let poll = 0; poll < 40; poll++) {
        await new Promise((res) => setTimeout(res, 3000));
        setAddMsg(ADD_STEPS[Math.min(1 + Math.floor(poll / 4), ADD_STEPS.length - 1)]);
        let s: Record<string, string> = { state: "running" };
        try {
          s = await fetch(`${API}/api/request-ticker-status?ticker=${tick}`).then((x) => x.json());
        } catch { /* transient - keep polling */ }
        if (s.state === "done") { window.location.href = `/ticker/${tick}`; return; }
        if (s.state === "error") {
          alert(s.error || "Couldn't add that ticker.");
          setAdding(false); return;
        }
      }
      alert(`Still pulling ${tick}'s history - it'll appear in All Stocks within a couple of minutes.`);
    } catch { alert("Connection hiccup - give it another try."); }
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

  const spotlightOrdered = (() => {
    if (!spot || tab === "news") return sorted;
    const idx = sorted.findIndex((r: Row) => r.ticker === spot.ticker);
    if (idx <= 0) return sorted;
    return [sorted[idx], ...sorted.slice(0, idx), ...sorted.slice(idx + 1)];
  })();

  const cols = COLUMNS[tab];

  // tailwind safelist: border-assay text-assay border-oxide text-oxide border-hazard text-hazard
  const sideItem = (t: { id: string; label: string }, color: string) => (
    <button key={t.id} onClick={() => setTab(t.id)}
      className={`w-full text-left font-display tracking-wide text-[17px] px-3 py-1.5 rounded-sm border-l-2 transition-colors ${
        tab === t.id
          ? `border-${color} text-${color} bg-tray`
          : "border-transparent text-ash hover:text-bone hover:bg-tray/60"}`}>
      {t.label}
    </button>
  );

  return (
    <div className="md:flex md:gap-6 md:items-start">
      {/* ---- Terminal sidebar (desktop) ---- */}
      <aside className="hidden md:block w-52 shrink-0 sticky top-16 self-start">
        <div className="bg-tray/40 border border-seam rounded-sm p-2.5 space-y-4">
          <div>
            <p className="text-ash text-[10px] uppercase tracking-[0.3em] px-3 pt-1 pb-1.5">Terminal</p>
            {sideItem({ id: "all-stocks", label: "All Stocks" }, "assay")}
          </div>
          <div>
            <p className="text-oxide text-[10px] uppercase tracking-[0.3em] px-3 pb-1.5 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-oxide inline-block" />Bullish Scanners
            </p>
            {BULLISH_TABS.map((t) => sideItem(t, "oxide"))}
          </div>
          <div>
            <p className="text-hazard text-[10px] uppercase tracking-[0.3em] px-3 pb-1.5 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-hazard inline-block" />Risk Factors
            </p>
            {RISK_TABS.map((t) => sideItem(t, "hazard"))}
          </div>
          <div className="border-t border-seam pt-2.5">
            <a href="/assayer"
               className="block font-display tracking-wide text-[17px] px-3 py-1.5 text-assay hover:bg-tray/60 rounded-sm">
              The Assayer &rarr;
            </a>
          </div>
        </div>
      </aside>

      {/* ---- Main column ---- */}
      <div className="flex-1 min-w-0">
      <WatchlistBar />

      {/* mobile scanner strip */}
      <div className="md:hidden flex gap-1.5 overflow-x-auto pb-2 mb-3 -mx-1 px-1">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`whitespace-nowrap font-display tracking-wide px-3 py-1 rounded-sm border text-sm ${
              tab === t.id ? "border-assay text-assay bg-tray" : "border-seam text-ash"}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div>
      <div className="flex flex-col md:flex-row gap-2 mb-3">
        <div className="relative flex-1">
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
                  {adding ? addMsg || "Fetching market data..." :
                    `Not tracked yet - add "${q.trim().toUpperCase()}" and pull its data now`}
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
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
          {spot && (
            <tr>
              <td colSpan={cols.length} className="!p-0">
                <div className="flex items-center gap-3 px-3 py-2 border-l-2 border-assay"
                     style={{ background: "linear-gradient(90deg, rgba(232,180,74,0.10), rgba(232,180,74,0.02))" }}>
                  <span className="bg-assay text-shale text-[9px] font-bold tracking-[0.2em] px-1.5 py-0.5 rounded-sm">SPOTLIGHT</span>
                  <a href={`/ticker/${spot.ticker}`} className="font-mono text-assay hover:underline">{spot.ticker}</a>
                  <span className="text-sm truncate">{spot.headline}</span>
                  <a href={`/story/${spot.ticker}`}
                     className="ml-auto bg-assay text-shale text-xs font-semibold px-3 py-1 rounded-sm font-display tracking-wide hover:opacity-90 whitespace-nowrap">
                    View the Story &rarr;
                  </a>
                  <span className="text-ash/60 text-[9px] whitespace-nowrap">Paid placement</span>
                </div>
              </td>
            </tr>
          )}
          {spotlightOrdered.map((r, i) => (
            <tr key={r.ticker ?? i}
                style={spot && r.ticker === spot.ticker
                  ? { background: "rgba(232,180,74,0.06)", boxShadow: "inset 2px 0 0 #E8B44A" }
                  : undefined}>
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
    </div>
    </div>
  );
}
