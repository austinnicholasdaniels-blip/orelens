"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Row = Record<string, any>;

const FEATURES = [
  { title: "Dilution Grades A-F", body: "Every company graded on cash runway, burn rate, and warrant overhang - recomputed nightly from filings and market data." },
  { title: "Unlock Calendar", body: "Every placement tracked from announcement to close, with the exact date the 4-month hold expires and the paper free-trades." },
  { title: "Stock Promotion Registry", body: "Disclosed investor-awareness and IR engagements across the Venture - who is being promoted, and how much they paid." },
  { title: "Cash & Share History", body: "Quarterly cash balances and share counts side by side: the dilution treadmill, visualized for every name." },
  { title: "Drill Intelligence", body: "Active programs, benchmark-beating intercepts, and jurisdiction percentile rankings parsed from the wire nightly." },
  { title: "Search Any Junior", body: "Type any TSX / TSX-V / CSE / ASX ticker. Not tracked yet? One click pulls its full history and builds the page." },
];

export default function Landing() {
  const [dq, setDq] = useState<Row | null>(null);
  const [unlocks, setUnlocks] = useState<Row[]>([]);
  const [promos, setPromos] = useState<Row[]>([]);
  const [movers, setMovers] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Row[]>([]);

  useEffect(() => {
    const get = (p: string) => fetch(`${API}${p}`).then((r) => r.json()).catch(() => null);
    get("/api/data-quality").then((d) => d && setDq(d));
    get("/api/scanners/unlock-calendar").then((d) => Array.isArray(d) && setUnlocks(d.slice(0, 5)));
    get("/api/scanners/stock-promotions").then((d) => {
      if (!Array.isArray(d)) return;
      const seen = new Set<string>();
      setPromos(d.filter((r) => !seen.has(r.ticker) && seen.add(r.ticker)).slice(0, 5));
    });
    get("/api/scanners/all-stocks").then((d) => Array.isArray(d) && setMovers(d.slice(0, 5)));
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const t = setTimeout(() => {
      fetch(`${API}/api/search?q=${encodeURIComponent(q)}`)
        .then((r) => r.json()).then(setHits).catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const Card = ({ title, link, children }: { title: string; link: string; children: React.ReactNode }) => (
    <div className="bg-tray border border-seam rounded-sm">
      <div className="flex items-baseline justify-between px-4 pt-3 pb-2 border-b border-seam">
        <p className="text-xs uppercase tracking-widest text-ash">{title}</p>
        <Link href={link} className="text-xs text-assay hover:underline">View all &rarr;</Link>
      </div>
      <div className="px-4 py-2">{children}</div>
    </div>
  );

  const Empty = ({ text }: { text: string }) => (
    <p className="text-ash text-sm py-4">{text}</p>
  );

  return (
    <div className="space-y-14">
      {/* Hero */}
      <section className="text-center pt-8">
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-4">Junior Mining Intelligence</p>
        <h1 className="font-display text-5xl md:text-6xl tracking-wide leading-tight">
          See dilution <span className="text-hazard">before</span> it hits.
        </h1>
        <p className="text-bone/90 max-w-2xl mx-auto mt-4 text-lg">
          Dilution grades, the Unlock Calendar, and the promotion registry for
          TSX-V and TSX mining stocks - built from filings and disclosures,
          updated every night.
        </p>

        {/* Fintel-style search front and center */}
        <div className="relative max-w-xl mx-auto mt-8">
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search any junior mining stock - ticker or name..."
            className="w-full bg-tray border border-seam rounded-sm px-5 py-3.5 text-base placeholder:text-ash focus:border-assay focus:outline-none" />
          {q.trim().length >= 2 && hits.length > 0 && (
            <div className="absolute z-10 mt-1 w-full bg-tray border border-seam rounded-sm shadow-lg text-left">
              {hits.map((h) => (
                <a key={h.ticker} href={`/ticker/${h.ticker}`}
                   className="flex items-baseline gap-3 px-4 py-2 hover:bg-shale text-sm">
                  <span className="font-mono text-assay">{h.ticker}</span>
                  <span>{h.name}</span>
                  <span className="text-ash text-xs ml-auto">{h.exchange}</span>
                </a>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-center gap-4 mt-6">
          <Link href="/dashboard"
            className="bg-assay text-shale font-semibold px-6 py-3 rounded-sm font-display text-lg tracking-wide hover:opacity-90">
            Open the Dashboard
          </Link>
        </div>
      </section>

      {/* Live stats band */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Companies Tracked", val: dq?.companies_tracked },
          { label: "Press Releases Indexed", val: dq?.press_releases_stored },
          { label: "Financings Tracked", val: dq?.financings_tracked },
          { label: "Priced Through", val: dq?.latest_price_day, str: true },
        ].map((s) => (
          <div key={s.label} className="bg-tray border border-seam rounded-sm p-4 text-center">
            <p className="font-display text-3xl text-assay">
              {s.val == null ? "\u2014" : s.str ? s.val : Number(s.val).toLocaleString()}
            </p>
            <p className="text-ash text-xs uppercase tracking-widest mt-1">{s.label}</p>
          </div>
        ))}
      </section>

      {/* Live data teasers */}
      <section className="grid md:grid-cols-3 gap-4">
        <Card title="Upcoming Unlocks" link="/dashboard">
          {unlocks.length === 0 ? <Empty text="Calendar loads as placements close." /> :
            unlocks.map((u) => (
              <a key={u.ticker + u.hold_expiry} href={`/ticker/${u.ticker}`}
                 className="flex items-baseline gap-2 py-1.5 text-sm hover:text-assay">
                <span className="font-mono text-assay">{u.ticker}</span>
                <span className="text-ash text-xs">{u.amount_m ? `$${u.amount_m}M` : u.kind}</span>
                <span className={`ml-auto text-xs ${u.days_until <= 14 ? "text-hazard" : "text-ash"}`}>
                  {u.days_until}d
                </span>
              </a>
            ))}
        </Card>
        <Card title="Active Stock Promotions" link="/dashboard">
          {promos.length === 0 ? <Empty text="Registry fills as engagements are disclosed." /> :
            promos.map((p) => (
              <a key={p.ticker} href={`/ticker/${p.ticker}`}
                 className="flex items-baseline gap-2 py-1.5 text-sm hover:text-assay">
                <span className="font-mono text-assay">{p.ticker}</span>
                <span className="text-ash text-xs truncate">{p.name}</span>
                <span className="ml-auto text-xs font-mono">
                  {p.amount ? `$${Number(p.amount).toLocaleString()}` : "\u2014"}
                </span>
              </a>
            ))}
        </Card>
        <Card title="Today's Movers" link="/dashboard">
          {movers.length === 0 ? <Empty text="Waking the data engine - refresh in ~30s." /> :
            movers.map((m) => (
              <a key={m.ticker} href={`/ticker/${m.ticker}`}
                 className="flex items-baseline gap-2 py-1.5 text-sm hover:text-assay">
                <span className="font-mono text-assay">{m.ticker}</span>
                <span className="text-ash text-xs">${m.price}</span>
                <span className={`ml-auto text-xs ${m.change_pct >= 0 ? "text-oxide" : "text-hazard"}`}>
                  {m.change_pct > 0 ? "+" : ""}{m.change_pct}%
                </span>
              </a>
            ))}
        </Card>
      </section>

      {/* Feature grid */}
      <section className="grid md:grid-cols-3 gap-4">
        {FEATURES.map((f) => (
          <div key={f.title} className="bg-tray border border-seam rounded-sm p-5">
            <h3 className="font-display text-xl tracking-wide text-assay mb-2">{f.title}</h3>
            <p className="text-sm text-bone/80 leading-relaxed">{f.body}</p>
          </div>
        ))}
      </section>

      {/* Trust strip */}
      <section className="text-center border-t border-seam pt-6 pb-2">
        <p className="text-ash text-sm">
          Every financial figure keeps its source URL for verification.
          OreLens is a research tool, not investment advice.
        </p>
      </section>
    </div>
  );
}
