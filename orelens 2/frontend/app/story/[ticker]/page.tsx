"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import TVChart from "@/components/TVChart";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Row = Record<string, any>;

export default function SponsorStory() {
  const params = useParams<{ ticker: string }>();
  const ticker = (params?.ticker ?? "").toString().toUpperCase();
  const [d, setD] = useState<Row | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    fetch(`${API}/api/story/${ticker}`)
      .then((r) => r.json())
      .then((x) => (x.error ? setErr(true) : setD(x)))
      .catch(() => setErr(true));
  }, [ticker]);

  if (err) return <p className="text-ash text-center py-20">Story not found.</p>;
  if (!d) return <p className="text-ash text-center py-20">Loading the story&hellip;</p>;

  return (
    <div className="max-w-4xl mx-auto space-y-10">
      {/* hero */}
      <div className="text-center pt-4">
        <span className="bg-assay text-shale text-[10px] font-bold tracking-[0.25em] px-2.5 py-1 rounded-sm">
          SPOTLIGHT STORY
        </span>
        <h1 className="font-display text-5xl tracking-wide mt-4">
          {d.name}
        </h1>
        <p className="text-ash mt-1">
          <span className="font-mono text-assay">{d.ticker}</span>
          <span className="font-mono text-xs">.{d.exchange}</span>
          {d.commodity && <> &middot; {d.commodity}</>}
          {d.jurisdiction && <> &middot; {d.jurisdiction}</>}
        </p>
        {d.headline && (
          <p className="font-display text-2xl text-assay mt-5">{d.headline}</p>
        )}
        {d.about && (
          <p className="text-bone/85 max-w-2xl mx-auto mt-4 leading-relaxed">{d.about}</p>
        )}
        <div className="flex items-center justify-center gap-3 mt-6">
          {d.website && (
            <a href={d.website} target="_blank" rel="noopener noreferrer"
               className="bg-assay text-shale font-display tracking-wide font-semibold px-5 py-2 rounded-sm hover:opacity-90">
              Visit {d.ticker} &rarr;
            </a>
          )}
          <a href={`/ticker/${d.ticker}`}
             className="border border-seam text-bone px-5 py-2 rounded-sm text-sm hover:border-assay hover:text-assay">
            Research profile
          </a>
        </div>
      </div>

      {/* chart */}
      <TVChart ticker={d.ticker} exchange={d.exchange} />

      {/* milestones */}
      {d.milestones?.length > 0 && (
        <div>
          <p className="text-ash text-xs uppercase tracking-[0.25em] mb-4">Key Milestones</p>
          <div className="relative pl-6 border-l border-assay/50 space-y-6">
            {d.milestones.map((m: Row, i: number) => (
              <div key={i} className="relative">
                <span className="absolute -left-[29px] top-1 w-2.5 h-2.5 rounded-full bg-assay" />
                <p className="font-mono text-assay text-xs">{m.date}</p>
                <p className="font-display text-xl tracking-wide">{m.title}</p>
                {m.desc && <p className="text-ash text-sm mt-0.5">{m.desc}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* key news */}
      {d.news?.length > 0 && (
        <div>
          <p className="text-ash text-xs uppercase tracking-[0.25em] mb-3">Key News</p>
          <div className="space-y-2">
            {d.news.map((n: Row, i: number) => (
              <a key={i} href={n.url || "#"} target="_blank" rel="noopener noreferrer"
                 className="block bg-tray border border-seam rounded-sm px-4 py-3 hover:border-assay">
                <span className="font-mono text-ash text-xs mr-3">{n.date}</span>
                <span className="text-bone">{n.headline}</span>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* snapshot strip */}
      {d.snapshot?.cash != null && (
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-tray border border-seam rounded-sm p-4 text-center">
            <p className="font-display text-2xl">${(d.snapshot.cash / 1e6).toFixed(1)}M</p>
            <p className="text-ash text-xs uppercase tracking-widest mt-1">Treasury &middot; {d.snapshot.as_of}</p>
          </div>
          <div className="bg-tray border border-seam rounded-sm p-4 text-center">
            <p className="font-display text-2xl">{(d.snapshot.shares_outstanding / 1e6).toFixed(1)}M</p>
            <p className="text-ash text-xs uppercase tracking-widest mt-1">Shares Outstanding</p>
          </div>
        </div>
      )}

      <p className="text-ash/70 text-[11px] text-center pb-6">
        Sponsored placement. Content provided in partnership with the company.
        Market data and filings via OreLens. Not investment advice.
      </p>
    </div>
  );
}
