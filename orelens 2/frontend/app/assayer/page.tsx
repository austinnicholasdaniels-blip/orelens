"use client";
import { useEffect, useState } from "react";
import BetaGate from "@/components/BetaGate";
import { sessionToken } from "@/components/watchlistClient";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const EXCHANGES = ["NYSE", "NASDAQ", "TSX", "TSXV", "CSE", "OTC"];
const LOADING_LINES = [
  "Crushing the sample\u2026",
  "Firing the furnace\u2026",
  "Weighing the dor\u00e9\u2026",
  "Reading the dilution seams\u2026",
];
type Row = Record<string, any>;

const GRADE_COLOR: Record<string, string> = {
  A: "text-oxide border-oxide", B: "text-oxide border-oxide",
  C: "text-assay border-assay", D: "text-hazard border-hazard",
  F: "text-hazard border-hazard",
};
const STATUS_ICON: Record<string, string> = { pass: "\u2713", warn: "\u26a0", fail: "\u2717" };
const STATUS_COLOR: Record<string, string> = {
  pass: "text-oxide", warn: "text-assay", fail: "text-hazard",
};

function AssayerInner() {
  const [ticker, setTicker] = useState("");
  const [exchange, setExchange] = useState("TSXV");
  const [price, setPrice] = useState("");
  const [thesis, setThesis] = useState("");
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState(0);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<Row | null>(null);
  const token = typeof document !== "undefined" ? sessionToken() : "";

  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setLine((l) => (l + 1) % LOADING_LINES.length), 1600);
    return () => clearInterval(id);
  }, [busy]);

  const run = async () => {
    setErr(""); setResult(null);
    const p = parseFloat(price);
    if (!ticker.trim()) { setErr("Which ticker?"); return; }
    if (!p || p <= 0) { setErr("Enter your entry price."); return; }
    if (thesis.trim().length < 20) { setErr("Give The Assayer a real thesis - a few sentences."); return; }
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/assayer`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ticker: ticker.trim(), exchange,
                               entry_price: p, thesis: thesis.trim() }),
      });
      const d = await r.json();
      if (d.ok) setResult(d);
      else setErr(d.error ?? "The furnace misfired - try again.");
    } catch { setErr("Could not reach the assay lab - try again in a moment."); }
    setBusy(false);
  };

  const a = result?.assay;

  return (
    <div className="max-w-3xl mx-auto space-y-8 pb-10">
      <div className="text-center pt-2">
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-2">OreLens AI</p>
        <h1 className="font-display text-5xl tracking-wide">
          The <span className="text-assay">Assayer</span>
        </h1>
        <p className="text-bone/85 mt-3 max-w-xl mx-auto">
          Bring your thesis. Leave with the truth. The Assayer grades your trade
          idea against the platform&apos;s dilution intelligence - runway, raises,
          promotions, unlocks - and tells you what the sample is really worth.
        </p>
      </div>

      {!token && (
        <div className="bg-tray border border-assay rounded-sm p-5 text-center">
          <p className="text-bone">The Assayer works from your member account.</p>
          <a href="/login" className="inline-block mt-3 bg-assay text-shale font-display tracking-wide font-semibold px-6 py-2 rounded-sm hover:opacity-90">
            Log in to assay &rarr;
          </a>
        </div>
      )}

      <div className="bg-tray border border-seam rounded-sm p-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <input value={ticker} placeholder="Ticker (e.g. VZLA)"
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            className="bg-shale border border-seam rounded-sm px-4 py-3 font-mono text-bone placeholder:text-ash placeholder:font-sans focus:border-assay outline-none" />
          <select value={exchange} onChange={(e) => setExchange(e.target.value)}
            className="bg-shale border border-seam rounded-sm px-4 py-3 text-bone focus:border-assay outline-none">
            {EXCHANGES.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <input value={price} placeholder="Entry price" inputMode="decimal"
            onChange={(e) => setPrice(e.target.value.replace(/[^0-9.]/g, ""))}
            className="bg-shale border border-seam rounded-sm px-4 py-3 font-mono text-bone placeholder:text-ash placeholder:font-sans focus:border-assay outline-none" />
        </div>
        <textarea value={thesis} rows={5}
          placeholder="Your thesis - why this trade works. Catalysts, timeline, what the market is missing&hellip;"
          onChange={(e) => setThesis(e.target.value)}
          className="w-full bg-shale border border-seam rounded-sm px-4 py-3 text-bone placeholder:text-ash focus:border-assay outline-none resize-y" />
        <button onClick={run} disabled={busy || !token}
          className="w-full bg-assay text-shale font-display tracking-wide font-semibold text-lg py-3 rounded-sm hover:opacity-90 disabled:opacity-60">
          {busy ? LOADING_LINES[line] : "Run the Assay \u2192"}
        </button>
        {err && <p className="text-hazard text-sm text-center">{err}</p>}
      </div>

      {result && a && (
        <div className="space-y-5">
          <div className="bg-tray border border-seam rounded-sm p-6 flex items-center gap-6 flex-wrap">
            <div className={`w-20 h-20 border-2 rounded-sm flex items-center justify-center font-display text-5xl ${GRADE_COLOR[a.grade] ?? "text-ash border-seam"}`}>
              {a.grade}
            </div>
            <div className="flex-1 min-w-[220px]">
              <p className="font-display text-2xl tracking-wide">{a.verdict}</p>
              <div className="mt-2 h-2 bg-shale rounded-sm overflow-hidden">
                <div className="h-full bg-assay" style={{ width: `${a.score ?? 0}%` }} />
              </div>
              <p className="text-ash text-xs mt-1">
                Assay score {a.score}/100 &middot; {result.ticker}
                {result.tracked ? "" : " \u00b7 not tracked yet - pulling its filings now; re-run in ~2 min for the full dilution read"}
              </p>
            </div>
          </div>

          <div className="bg-tray border border-assay rounded-sm p-5">
            <p className="text-assay text-xs uppercase tracking-[0.25em] mb-2">Dilution Risk</p>
            <p className="text-bone/90 leading-relaxed">{a.dilution_risk}</p>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="bg-tray border border-seam rounded-sm p-5">
              <p className="text-oxide text-xs uppercase tracking-[0.25em] mb-2">Strengths</p>
              {(a.strengths ?? []).map((s: string, i: number) => (
                <p key={i} className="text-sm text-bone/90 mb-1.5">
                  <span className="text-oxide mr-1.5">+</span>{s}</p>
              ))}
            </div>
            <div className="bg-tray border border-seam rounded-sm p-5">
              <p className="text-hazard text-xs uppercase tracking-[0.25em] mb-2">Risks</p>
              {(a.risks ?? []).map((s: string, i: number) => (
                <p key={i} className="text-sm text-bone/90 mb-1.5">
                  <span className="text-hazard mr-1.5">&ndash;</span>{s}</p>
              ))}
            </div>
          </div>

          <div className="bg-tray border border-seam rounded-sm p-5">
            <p className="text-ash text-xs uppercase tracking-[0.25em] mb-3">The Checklist</p>
            {(a.checklist ?? []).map((c2: Row, i: number) => (
              <div key={i} className="flex items-center gap-3 py-1.5 border-b border-seam/50 last:border-0">
                <span className={`font-mono ${STATUS_COLOR[c2.status] ?? "text-ash"}`}>
                  {STATUS_ICON[c2.status] ?? "?"}
                </span>
                <span className="text-sm text-bone/90">{c2.item}</span>
              </div>
            ))}
          </div>

          <div className="bg-tray border border-seam rounded-sm p-5">
            <p className="text-ash text-xs uppercase tracking-[0.25em] mb-2">The Assayer&apos;s Feedback</p>
            <p className="text-bone/90 leading-relaxed">{a.feedback}</p>
          </div>

          <p className="text-ash text-xs text-center">
            {result.assays_left_today} assays left today &middot; The Assayer grades
            idea quality from filings-based data. Research tool, not investment advice.
          </p>
        </div>
      )}
    </div>
  );
}

export default function AssayerPage() {
  return <BetaGate><AssayerInner /></BetaGate>;
}
