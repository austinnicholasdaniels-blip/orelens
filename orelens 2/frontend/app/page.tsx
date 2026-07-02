"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FEATURES = [
  { title: "Dilution Grades A-F", body: "Every company graded on cash runway, burn rate, and warrant overhang - recomputed nightly from real filings and market data." },
  { title: "Warrant Overhang Maps", body: "Every warrant tranche plotted by strike and expiry. Green = in the money and coming. Grey = the resistance levels waiting overhead." },
  { title: "Share Count History", body: "Quarterly shares outstanding for every name, so you can see exactly how many new shares hit the market - and when." },
  { title: "AI Filing Extraction", body: "MD&As and financial statements read automatically: cash, burn, and full warrant tables pulled straight from the source documents." },
  { title: "Purpose-Built Scanners", body: "Best Bang-for-Buck, Most Dilutive, Active Drill Programs, and High-Grade Breakouts - screens designed for juniors, not adapted from large caps." },
  { title: "Search Any Junior", body: "Type any TSX / TSX-V / CSE / ASX ticker. Not tracked yet? One click pulls its full history and builds the page on the spot." },
];

export default function Landing() {
  const [stats, setStats] = useState<{ tracked: number | null }>({ tracked: null });

  useEffect(() => {
    fetch(`${API}/api/scanners/value-momentum`)
      .then((r) => r.json())
      .then((rows) => setStats({ tracked: Array.isArray(rows) ? rows.length : null }))
      .catch(() => {});
  }, []);

  return (
    <div className="space-y-16">
      {/* Hero */}
      <section className="text-center pt-10 pb-4">
        <p className="text-assay text-xs tracking-[0.3em] uppercase mb-4">Junior Mining Intelligence</p>
        <h1 className="font-display text-5xl md:text-6xl tracking-wide leading-tight">
          See dilution <span className="text-hazard">before</span> it hits.
        </h1>
        <p className="text-bone/90 max-w-2xl mx-auto mt-5 text-lg">
          OreLens turns regulatory filings into live intelligence on TSX and TSX-V
          exploration stocks: dilution grades, warrant overhang maps, drill-result
          scanners, and quarterly share-count history - updated every night.
        </p>
        <div className="flex items-center justify-center gap-4 mt-8">
          <Link href="/dashboard"
            className="bg-assay text-shale font-semibold px-6 py-3 rounded-sm font-display text-lg tracking-wide hover:opacity-90">
            Open the Scanner
          </Link>
          <Link href="/dashboard"
            className="border border-assay/40 px-6 py-3 rounded-sm font-display text-lg tracking-wide text-assay hover:border-assay hover:bg-assay/10">
            Search a Stock
          </Link>
        </div>
        <p className="text-ash text-sm mt-6">
          {stats.tracked ? `${stats.tracked}+ graded juniors` : "40+ juniors tracked"} &middot; TSX &middot; TSX-V &middot; CSE &middot; ASX &middot; updated nightly
        </p>
      </section>

      {/* The problem strip */}
      <section className="bg-tray border border-seam rounded-sm p-8 text-center">
        <p className="text-bone/90 max-w-3xl mx-auto text-lg leading-relaxed">
          Junior miners live and die by the treasury. The warrant table is buried in a
          PDF footnote, the burn rate takes four statements to reconstruct, and by the
          time retail sees the financing, the shares are already trading.
          <span className="text-assay"> OreLens reads the filings so you don't have to.</span>
        </p>
      </section>

      {/* Features */}
      <section>
        <h2 className="font-display text-3xl tracking-wide text-center mb-8">What's inside</h2>
        <div className="grid md:grid-cols-3 gap-5">
          {FEATURES.map((f) => (
            <div key={f.title} className="bg-tray border border-seam rounded-sm p-5 hover:border-assay/50 transition-colors">
              <h3 className="font-display text-xl tracking-wide text-assay mb-2">{f.title}</h3>
              <p className="text-sm text-bone/80 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How grading works */}
      <section className="bg-tray border border-seam rounded-sm p-8">
        <h2 className="font-display text-3xl tracking-wide text-center mb-6">How the grade works</h2>
        <div className="grid md:grid-cols-3 gap-6 text-center">
          <div>
            <p className="font-display text-4xl text-assay">A</p>
            <p className="text-sm text-bone/80 mt-2">12+ months of runway or fully-funded programs, warrant overhang under 15% of float.</p>
          </div>
          <div>
            <p className="font-display text-4xl text-ash">B / C</p>
            <p className="text-sm text-bone/80 mt-2">Funding secure but overhang building, or runway tightening toward the next raise window.</p>
          </div>
          <div>
            <p className="font-display text-4xl text-hazard">D / F</p>
            <p className="text-sm text-bone/80 mt-2">Months of cash left, heavy warrant stacks, or both - a financing is coming, priced against you.</p>
          </div>
        </div>
        <p className="text-center mt-6">
          <Link href="/dashboard" className="text-assay hover:underline">
            See today's grades &rarr;
          </Link>
        </p>
      </section>

      {/* Footer */}
      <footer className="text-center text-xs text-ash pb-8 space-y-2">
        <p>OreLens is a research tool. Nothing on this site is investment advice.
           Data is derived from public filings and market feeds and may contain errors or lags - verify against source documents.</p>
        <p>&copy; 2026 OreLens</p>
      </footer>
    </div>
  );
}
