"use client";
import { useEffect, useState } from "react";
import { getTicker, fmt } from "@/lib/api";
import PriceChart from "@/components/PriceChart";
import DilutionGauge from "@/components/DilutionGauge";
import WarrantOverhangMap from "@/components/WarrantOverhangMap";
import DrillTimeline from "@/components/DrillTimeline";

export default function TickerPage({ params }: { params: { symbol: string } }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getTicker(params.symbol).then(setData).catch(() => setError("Ticker not found or API offline."));
  }, [params.symbol]);

  if (error) return <p className="text-hazard">{error}</p>;
  if (!data) return <p className="text-ash">Loading core samples…</p>;

  const { company, prices, grade, capital, warrants, program, drill_results, comparison } = data;

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
        </div>
        <div className="bg-tray border border-seam rounded-sm p-4 h-fit">
          <p className="text-xs uppercase tracking-widest text-ash mb-3">Capital Structure</p>
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-ash">Shares Outstanding</dt><dd className="font-mono text-right">{fmt.shares(capital.shares_outstanding)}</dd>
            <dt className="text-ash">Fully Diluted</dt><dd className="font-mono text-right">{fmt.shares(capital.fully_diluted)}</dd>
            <dt className="text-ash">Cash Balance</dt><dd className="font-mono text-right">{fmt.money(capital.cash)}</dd>
            <dt className="text-ash">Monthly Burn</dt><dd className="font-mono text-right">{fmt.money(capital.monthly_burn)}</dd>
            <dt className="text-ash">Theoretical Cash from Warrants</dt><dd className="font-mono text-right text-oxide">{fmt.money(capital.theoretical_warrant_cash)}</dd>
          </dl>
        </div>
      </div>

      <DrillTimeline program={program} results={drill_results} comparison={comparison} />
    </div>
  );
}
