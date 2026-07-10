"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FEATURES = [
  "All 11 scanners - Dilution Risk, Burn League, Unlock Calendar, and more",
  "Dilution grades (A-F) on 200+ mining companies, recomputed nightly",
  "The Unlock Calendar - see paper free-trading before it hits the market",
  "The Promotion Registry - every disclosed paid campaign, with dollar amounts",
  "Full company profiles - capital structure, runway, financing history, TradingView charts",
  "\"This Week in Dilution\" - the weekly intelligence digest",
  "Watchlist across every device you use",
  "Six exchanges: TSX, TSX-V, CSE, NYSE, NASDAQ, ASX",
];

const FAQS = [
  ["Why is the price this low?",
   "It's launch pricing for founding members. When the launch window closes, new members pay $725/year - but your rate locks at $97.99/year for as long as you stay subscribed."],
  ["Can I cancel?",
   "Anytime, in two clicks, from the receipt Stripe emails you. No calls, no forms."],
  ["Is this investment advice?",
   "No. OreLens is a research platform. We surface what filings and disclosures say - grades, runways, unlocks, and promotions - so you can make your own decisions."],
  ["Where does the data come from?",
   "Licensed market data and company filings, refreshed nightly. Every figure keeps its source."],
];

export default function Pricing() {
  const [checkout, setCheckout] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/billing-config`)
      .then((r) => r.json())
      .then((d) => { setCheckout(d.checkout_url); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  return (
    <div className="max-w-3xl mx-auto space-y-12 pb-10">
      <div className="text-center pt-6">
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-3">Launch Pricing</p>
        <h1 className="font-display text-5xl tracking-wide">Become a Founding Member</h1>
        <p className="text-bone/85 max-w-xl mx-auto mt-4">
          Full access to the dilution-intelligence terminal for mining investors.
          One plan. Everything included.
        </p>
      </div>

      <div className="bg-tray border border-assay rounded-sm p-8 text-center relative overflow-hidden">
        <span className="absolute top-4 right-4 bg-assay text-shale text-[10px] font-bold tracking-[0.2em] px-2 py-1 rounded-sm">
          FOUNDING MEMBER
        </span>
        <p className="text-ash text-sm">
          <span className="line-through">$725/year</span> after the launch window
        </p>
        <p className="font-display text-6xl tracking-wide mt-2">
          $97.99<span className="text-2xl text-ash">/year</span>
        </p>
        <p className="text-oxide text-sm mt-2">
          Locks in for life &middot; that&apos;s $8.17/month for the full terminal
        </p>

        {checkout ? (
          <a href={checkout}
             className="inline-block mt-6 bg-assay text-shale font-display tracking-wide font-semibold text-lg px-10 py-3 rounded-sm hover:opacity-90">
            Subscribe &rarr;
          </a>
        ) : (
          <span
             className="inline-block mt-6 bg-assay/40 text-shale font-display tracking-wide font-semibold text-lg px-10 py-3 rounded-sm cursor-default">
            {loaded ? "Checkout opens shortly" : "Loading\u2026"}
          </span>
        )}
        <p className="text-ash text-xs mt-3">
          {checkout
            ? "Secure checkout by Stripe. Cancel anytime."
            : "Secure Stripe checkout is being connected. Members log in above."}
        </p>
      </div>

      <div className="bg-tray border border-seam rounded-sm p-6 md:flex items-center gap-6">
        <div className="md:w-1/3">
          <p className="text-ash text-xs uppercase tracking-[0.3em]">Members only</p>
          <p className="font-display text-3xl tracking-wide mt-1">The <span className="text-assay">Assayer</span></p>
          <p className="text-oxide text-sm mt-1">Bring your thesis. Leave with the truth.</p>
        </div>
        <p className="text-bone/85 leading-relaxed mt-3 md:mt-0 md:flex-1">
          Type in your trade idea - ticker, entry, thesis - and our AI grades it
          A to F against the platform&apos;s own dilution database: runway vs. your
          timeline, raises announced but not closed, paid promotions running,
          paper unlocking. Generic chatbots can&apos;t see any of that. The Assayer
          reads the filings so your thesis gets tested, not flattered.
        </p>
      </div>

      <div>
        <p className="text-ash text-xs uppercase tracking-[0.25em] mb-4 text-center">Everything included</p>
        <div className="grid sm:grid-cols-2 gap-3">
          {FEATURES.map((f) => (
            <div key={f} className="flex gap-2.5 bg-tray border border-seam rounded-sm px-4 py-3">
              <span className="text-oxide">{"\u2713"}</span>
              <span className="text-sm text-bone/90">{f}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="text-ash text-xs uppercase tracking-[0.25em] mb-4 text-center">Questions</p>
        <div className="space-y-3">
          {FAQS.map(([q, a]) => (
            <div key={q} className="bg-tray border border-seam rounded-sm px-5 py-4">
              <p className="font-semibold text-bone">{q}</p>
              <p className="text-ash text-sm mt-1.5 leading-relaxed">{a}</p>
            </div>
          ))}
        </div>
      </div>

      <p className="text-ash/70 text-[11px] text-center">
        OreLens is a research platform, not investment advice. Subscriptions renew
        annually and can be cancelled anytime via Stripe.
      </p>
    </div>
  );
}
