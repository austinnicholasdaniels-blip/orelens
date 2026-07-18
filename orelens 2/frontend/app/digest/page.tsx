"use client";
import { useEffect, useState } from "react";
import DataDisclaimer from "@/components/DataDisclaimer";
import ConversionBand from "@/components/ConversionBand";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Row = Record<string, any>;

export default function Digest() {
  const [d, setD] = useState<Row | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/digest/weekly`).then((r) => r.json()).then(setD).catch(() => setErr(true));
  }, []);

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div>
      <p className="text-ash text-xs uppercase tracking-[0.25em] mb-2">{title}</p>
      <div className="bg-tray border border-seam rounded-sm overflow-x-auto">{children}</div>
    </div>
  );
  const T = ({ headers, children }: { headers: string[]; children: React.ReactNode }) => (
    <table className="core-tray w-full">
      <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  );
  const Tk = ({ t }: { t: string }) => (
    <a href={`/ticker/${t}`} className="font-mono text-assay hover:underline">{t}</a>
  );

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      <div className="text-center">
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-2">The OreLens Weekly</p>
        <h1 className="font-display text-4xl tracking-wide">This Week in Dilution</h1>
        {d && <p className="text-ash text-sm mt-2">
          Week of {d.week_of} &middot; {d.counts.companies} companies tracked &middot;{" "}
          {d.counts.unlocks_14d} unlocks inside 14 days &middot; {d.counts.promos_week} new promotions
        </p>}
      </div>

      {err && <p className="text-ash text-center">The data engine is waking - refresh in ~30s.</p>}
      {!d && !err && <p className="text-ash text-center">Assembling this week&apos;s intelligence&hellip;</p>}

      {d && d.unlocks.length > 0 && (
        <Section title="Unlocks hitting in the next 14 days">
          <T headers={["Ticker", "Company", "Size", "Free-trades"]}>
            {d.unlocks.map((u: Row, i: number) => (
              <tr key={i}><td><Tk t={u.ticker} /></td><td>{u.name}</td>
                <td className="font-mono">{u.amount_m ? `$${u.amount_m}M` : "\u2014"}</td>
                <td className={`font-mono ${u.days <= 7 ? "text-hazard" : "text-ash"}`}>
                  {u.days}d &middot; {u.unlocks}</td></tr>
            ))}
          </T>
        </Section>
      )}

      {d && d.promotions.length > 0 && (
        <Section title="New paid promotions disclosed">
          <T headers={["Ticker", "Company", "Firm", "Paid"]}>
            {d.promotions.map((p: Row, i: number) => (
              <tr key={i}><td><Tk t={p.ticker} /></td><td>{p.name}</td>
                <td>{p.firm ?? "\u2014"}</td>
                <td className="font-mono">{p.paid ? `$${Number(p.paid).toLocaleString()}` : "\u2014"}</td></tr>
            ))}
          </T>
        </Section>
      )}

      {d && d.raises.length > 0 && (
        <Section title="Fresh raises this week">
          <T headers={["Ticker", "Company", "Size", "Status"]}>
            {d.raises.map((r: Row, i: number) => (
              <tr key={i}><td><Tk t={r.ticker} /></td><td>{r.name}</td>
                <td className="font-mono">{r.amount_m ? `$${r.amount_m}M` : "\u2014"}</td>
                <td className={r.status === "announced" ? "text-hazard text-xs font-semibold" : "text-ash text-xs"}>
                  {r.status.toUpperCase()}</td></tr>
            ))}
          </T>
        </Section>
      )}

      {d && d.grade_moves.length > 0 && (
        <Section title="Grade moves">
          <T headers={["Ticker", "Company", "Move"]}>
            {d.grade_moves.map((m: Row, i: number) => (
              <tr key={i}><td><Tk t={m.ticker} /></td><td>{m.name}</td>
                <td className={`font-mono ${m.direction === "up" ? "text-oxide" : "text-hazard"}`}>
                  {m.from} &rarr; {m.to}</td></tr>
            ))}
          </T>
        </Section>
      )}

      {d && d.shortest_fuses.length > 0 && (
        <Section title="Shortest fuses (adjusted runway)">
          <T headers={["Ticker", "Company", "Runway", "Burn"]}>
            {d.shortest_fuses.map((x: Row, i: number) => (
              <tr key={i}><td><Tk t={x.ticker} /></td><td>{x.name}</td>
                <td className={`font-mono ${x.runway_m <= 6 ? "text-hazard" : ""}`}>{x.runway_m} mo</td>
                <td className="font-mono text-ash">${Number(x.burn).toLocaleString()}/mo</td></tr>
            ))}
          </T>
        </Section>
      )}

      {d && d.scoreboard.median_during != null && (
        <div className="bg-tray border border-assay rounded-sm p-4 text-sm">
          <span className="text-assay font-semibold">The pattern: </span>
          across {d.scoreboard.campaigns} tracked campaigns, the median promoted stock moved{" "}
          {d.scoreboard.median_during > 0 ? "+" : ""}{d.scoreboard.median_during}% during its campaign
          {d.scoreboard.median_after != null && <> and {d.scoreboard.median_after > 0 ? "+" : ""}
          {d.scoreboard.median_after}% in the 30 days after it ended</>}.{" "}
          <a href="/research/promotions" className="text-assay hover:underline">Full scoreboard &rarr;</a>
        </div>
      )}

      <p className="text-ash text-xs text-center">
        Assembled automatically from filings, disclosures, and market data.
        Research tool, not investment advice.
      </p>
      <ConversionBand context="Get this intelligence every week - plus the terminal behind it." />
      <DataDisclaimer variant="digest" />
    </div>
  );
}
