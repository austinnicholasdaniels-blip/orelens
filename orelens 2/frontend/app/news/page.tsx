"use client";
import { useEffect, useState } from "react";
import { getScanner } from "@/lib/api";

export default function NewsPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getScanner("news", {}).then(setRows).catch(() =>
      setError("Couldn't reach the API. It may be waking up - retry in ~30s."));
  }, []);

  return (
    <div>
      <h1 className="font-display text-3xl tracking-wide mb-1">Mining News Wire</h1>
      <p className="text-ash text-sm mb-5 max-w-3xl">
        Every press release from the Newsfile mining, precious metals, and energy metals wires,
        refreshed nightly at 11 PM ET. Tickers link to full company profiles when a release matches
        a tracked name; the pickaxe marks drill-start announcements.
      </p>
      {error && <p className="text-hazard text-sm mb-4">{error}</p>}
      <table className="core-tray w-full">
        <thead>
          <tr><th>Published</th><th>Ticker</th><th>Headline</th><th>Wire</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><span className="text-xs text-ash font-mono">{(r.published ?? "").slice(0, 16).replace("T", " ")}</span></td>
              <td className="font-mono">
                {r.ticker ? (
                  <a href={`/ticker/${r.ticker}`} className="text-assay hover:underline">
                    {r.ticker}<span className="text-ash text-xs">.{r.exchange}</span>
                  </a>
                ) : (<span className="text-ash">-</span>)}
              </td>
              <td>
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="hover:text-assay hover:underline">
                  {r.headline}{r.drill_start ? " \u26cf" : ""}
                </a>
              </td>
              <td><span className="text-xs text-ash">{r.wire}</span></td>
            </tr>
          ))}
          {!error && rows.length === 0 && (
            <tr><td colSpan={4} className="text-ash text-center py-8">
              No press releases collected yet today. The wire sync runs nightly at 11 PM ET.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

