"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Row = Record<string, any>;

export default function PromotionScoreboard() {
  const [data, setData] = useState<Row | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/research/promotion-scoreboard`)
      .then((r) => r.json()).then(setData).catch(() => setErr(true));
  }, []);

  const s = data?.summary;
  const rows: Row[] = data?.campaigns ?? [];
  const pct = (v: any) =>
    v == null ? "\u2014" : (
      <span className={v >= 0 ? "text-oxide" : "text-hazard"}>
        {v > 0 ? "+" : ""}{v}%
      </span>
    );

  return (
    <div className="space-y-8">
      <div>
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-2">OreLens Research</p>
        <h1 className="font-display text-4xl tracking-wide">What Happens to Promoted Mining Stocks</h1>
        <p className="text-bone/80 max-w-2xl mt-2">
          Every disclosed paid-promotion campaign in the OreLens registry, matched
          against the stock&apos;s own price history: the return while the campaign ran,
          and the 30 days after it ended. Computed from filings and disclosures -
          updated nightly.
        </p>
      </div>

      {err && <p className="text-ash">The data engine is waking up - refresh in ~30 seconds.</p>}

      {s && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Campaigns Tracked", val: s.campaigns_analyzed, plain: true },
            { label: "Median Return During", val: s.median_return_during_pct },
            { label: "Median 30d After End", val: s.median_return_30d_after_pct },
            { label: "Ended w/ After Data", val: s.campaigns_ended_with_after_data, plain: true },
          ].map((x) => (
            <div key={x.label} className="bg-tray border border-seam rounded-sm p-4 text-center">
              <p className="font-display text-3xl">
                {x.plain ? (x.val ?? "\u2014") : pct(x.val)}
              </p>
              <p className="text-ash text-xs uppercase tracking-widest mt-1">{x.label}</p>
            </div>
          ))}
        </div>
      )}

      {s?.median_return_during_pct != null && s?.median_return_30d_after_pct != null && (
        <div className="bg-tray border border-assay rounded-sm p-4">
          <p className="text-sm">
            <span className="text-assay font-semibold">The pattern: </span>
            the median promoted stock moved {s.median_return_during_pct > 0 ? "+" : ""}
            {s.median_return_during_pct}% while its campaign ran, then
            {" "}{s.median_return_30d_after_pct > 0 ? "+" : ""}
            {s.median_return_30d_after_pct}% in the 30 days after the promotion ended.
            Know when the music stops.
          </p>
        </div>
      )}

      <div className="bg-tray border border-seam rounded-sm overflow-x-auto">
        <table className="core-tray w-full">
          <thead>
            <tr>
              <th>Ticker</th><th>Company</th><th>Announced</th><th>Ends</th>
              <th>Paid ($)</th><th>During</th><th>30d After</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><a href={`/ticker/${r.ticker}`} className="font-mono text-assay hover:underline">{r.ticker}</a></td>
                <td className="max-w-[220px] truncate">{r.name}</td>
                <td className="font-mono text-xs">{r.announced}</td>
                <td className="font-mono text-xs">{r.ends ?? "\u2014"}</td>
                <td className="font-mono">{r.amount ? Number(r.amount).toLocaleString() : "\u2014"}</td>
                <td className="font-mono">{pct(r.return_during_pct)}</td>
                <td className="font-mono">{pct(r.return_30d_after_pct)}</td>
                <td>
                  <span className={r.status === "ACTIVE" ? "text-hazard text-xs font-semibold" : "text-ash text-xs"}>
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !err && (
              <tr><td colSpan={8} className="text-ash py-6 text-center">
                Scoreboard fills as campaigns are disclosed and price history accrues.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-ash text-xs">
        Returns measured from the closest trading day to each disclosure. Research
        tool, not investment advice. Source URLs available on each company page.
      </p>
    </div>
  );
}
