"use client";
import { useEffect, useState } from "react";
import { getTicker, fmt } from "@/lib/api";
import PriceChart from "@/components/PriceChart";
import DilutionGauge from "@/components/DilutionGauge";
import WarrantOverhangMap from "@/components/WarrantOverhangMap";
import SharesHistoryChart from "@/components/SharesHistoryChart";
import CashHistoryChart from "@/components/CashHistoryChart";
import DrillTimeline from "@/components/DrillTimeline";
import BetaGate from "@/components/BetaGate";

export default function TickerPage({ params }: { params: { symbol: string } }) {
  return <BetaGate><TickerInner params={params} /></BetaGate>;
}

function TickerInner({ params }: { params: { symbol: string } }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getTicker(params.symbol).then(setData).catch(() => setError("Ticker not found or API offline."));
  }, [params.symbol]);

  if (error) return <p className="text-hazard">{error}</p>;
  if (!data) return <p className="text-ash">Loading core samples…</p>;

  const { company, prices, grade, capital, warrants, program, drill_results, comparison } = data;
  const ds = data.dilution_stats ?? {};
  const financings = data.financings ?? [];
  const promotions = data.promotions ?? [];
  const activePromo = promotions.find((p: any) => p.active);
  const today = new Date();
  const upcoming = financings.filter((f: any) => f.closed && f.hold_expiry && new Date(f.hold_expiry) >= today);
  const daysTo = (d: string) => Math.ceil((new Date(d).getTime() - today.getTime()) / 86400000);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-4 flex-wrap">
        <h1 className="font-display text-4xl tracking-wide">
          {company.ticker}<span className="text-ash text-2xl">.{company.exchange}</span>
        </h1>
        <span className="text-bone/90">{company.name}</span>
        <span className="text-ash text-sm">{company.project} · {company.commodity} · {company.jurisdiction}</span>
        <span className={`text-xs uppercase tracking-widest ${company.jurisdiction_tier === "Tier 1" ? "text-oxide" : "text-hazard"}`}>
          {company.jurisdiction_tier}
        </span>
      </div>

      <PriceChart prices={prices} />

      <div className="grid md:grid-cols-2 gap-6">
        <div className="space-y-6">
          <DilutionGauge grade={grade} />
          <WarrantOverhangMap warrants={warrants} />
          <SharesHistoryChart history={data.shares_history} />
          <CashHistoryChart history={data.cash_history} />
        </div>
        <div className="space-y-6 h-fit">
        <div className="bg-tray border border-seam rounded-sm p-4">
          <p className="text-xs uppercase tracking-widest text-ash mb-3">Capital Structure</p>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-ash">Shares Outstanding</dt><dd className="font-mono text-right">{fmt.shares(capital.shares_outstanding)}</dd>
            <dt className="text-ash">Fully Diluted</dt><dd className="font-mono text-right">{fmt.shares(capital.fully_diluted)}</dd>
            <dt className="text-ash">Cash Balance</dt><dd className="font-mono text-right">{fmt.money(capital.cash)}</dd>
            <dt className="text-ash">Monthly Burn</dt><dd className="font-mono text-right">{fmt.money(capital.monthly_burn)}</dd>
            <dt className="text-ash">Theoretical Cash from Warrants</dt><dd className="font-mono text-right text-oxide">{fmt.money(capital.theoretical_warrant_cash)}</dd>
          </dl>
        </div>

        <div className="bg-tray border border-seam rounded-sm p-4">
          <p className="text-xs uppercase tracking-widest text-ash mb-3">Dilution Profile</p>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-ash">Share Growth (1y)</dt>
            <dd className={`font-mono text-right ${(ds.shares_growth_1y_pct ?? 0) > 10 ? "text-hazard" : ""}`}>
              {ds.shares_growth_1y_pct != null ? `+${ds.shares_growth_1y_pct}%` : "\u2014"}</dd>
            <dt className="text-ash">Share Growth (3y)</dt>
            <dd className={`font-mono text-right ${(ds.shares_growth_3y_pct ?? 0) > 30 ? "text-hazard" : ""}`}>
              {ds.shares_growth_3y_pct != null ? `+${ds.shares_growth_3y_pct}%` : "\u2014"}</dd>
            <dt className="text-ash">Ownership Drag (3y)</dt>
            <dd className="font-mono text-right text-hazard">
              {ds.ownership_drag_3y_pct != null ? `\u2212${ds.ownership_drag_3y_pct}%` : "\u2014"}</dd>
            <dt className="text-ash">Est. Capital Raised (3y)</dt>
            <dd className="font-mono text-right">
              {ds.est_capital_raised_3y_m != null ? `$${ds.est_capital_raised_3y_m}M` : "\u2014"}</dd>
            <dt className="text-ash">Runway</dt>
            <dd className="font-mono text-right">
              {ds.adjusted_runway_m != null
                ? `${ds.adjusted_runway_m} mo (incl. $${ds.raised_since_snapshot_m}M raised)`
                : ds.runway_m != null ? `${ds.runway_m} mo` : "\u2014"}</dd>
          </dl>
          {(ds.raise_events_3y ?? []).length > 0 && (
            <div className="mt-3 pt-3 border-t border-seam">
              <p className="text-xs uppercase tracking-widest text-ash mb-2">Issuance Events (3y)</p>
              {ds.raise_events_3y.map((e: any, i: number) => (
                <div key={i} className="flex items-baseline gap-3 text-xs py-1">
                  <span className="font-mono text-ash">{e.date}</span>
                  <span className="text-hazard">+{e.pct}%</span>
                  <span className="text-ash">{e.shares_added_m}M shares</span>
                  {e.est_raised_m != null && (
                    <span className="ml-auto font-mono">~${e.est_raised_m}M</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {activePromo && (
          <div className="bg-tray border border-hazard rounded-sm p-4">
            <p className="text-xs uppercase tracking-widest text-hazard mb-2">&#9888; Active Stock Promotion</p>
            <p className="text-sm">
              {activePromo.amount
                ? `Disclosed paid promotion: $${Number(activePromo.amount).toLocaleString()}`
                : "Disclosed paid promotion (amount not stated in disclosure headline)"}
            </p>
            <a href={activePromo.url} target="_blank" rel="noopener noreferrer" className="text-xs text-assay hover:underline">disclosure</a>
          </div>
        )}
        <div className="bg-tray border border-seam rounded-sm p-4">
          <p className="text-xs uppercase tracking-widest text-ash mb-3">Financings &amp; Unlocks</p>
          {upcoming.map((f: any, i: number) => (
            <div key={`u${i}`} className={`mb-3 px-3 py-2 rounded-sm border text-sm ${daysTo(f.hold_expiry) <= 14 ? "border-hazard text-hazard" : "border-assay text-assay"}`}>
              &#9888; {f.amount && f.price ? `~${(f.amount / f.price / 1e6).toFixed(1)}M shares` : "Placement paper"} free-trading on <span className="font-mono">{f.hold_expiry}</span> ({daysTo(f.hold_expiry)}d)
            </div>
          ))}
          {financings.length === 0 && (
            <p className="text-ash text-sm">No financings detected in the last several months of news.</p>
          )}
          {financings.map((f: any, i: number) => (
            <div key={i} className="border-t border-seam py-2 text-sm flex flex-wrap items-baseline gap-x-3">
              <span className="capitalize">{f.kind}</span>
              <span className="font-mono">{f.amount ? `$${(f.amount / 1e6).toFixed(1)}M` : "\u2014"}</span>
              {f.price != null && <span className="text-ash">@ ${f.price}</span>}
              {f.warrant_strike != null && <span className="text-ash">wt ${f.warrant_strike}</span>}
              <span className={`text-xs uppercase tracking-widest ${f.closed ? "text-oxide" : "text-ash"}`}>
                {f.closed ? `Closed ${f.close_date ?? ""}` : `Announced ${f.announced}`}
              </span>
              {f.closed && f.hold_expiry && (
                <span className="text-xs text-ash">free-trading {f.hold_expiry}</span>
              )}
              <a href={f.url} target="_blank" rel="noopener noreferrer" className="text-xs text-assay hover:underline ml-auto">source</a>
            </div>
          ))}
        </div>
        </div>
      </div>

      <DrillTimeline program={program} results={drill_results} comparison={comparison} />
    </div>
  );
}
