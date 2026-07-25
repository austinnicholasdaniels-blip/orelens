import { redirect } from "next/navigation";

export const metadata = {
  title: "Track Record — What Dilution Actually Did | OreLens",
  description:
    "Every company OreLens tracks: how much their share count grew, and what the stock did. Computed from filings — no selection, no cherry-picking.",
};

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://orelens-api.onrender.com";

async function getRecord() {
  try {
    const r = await fetch(`${API}/api/track-record?window=30`, {
      next: { revalidate: 3600 },
    });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

const Stat = ({ k, v, tone = "" }: { k: string; v: string; tone?: string }) => (
  <div className="bg-tray border border-seam rounded-sm p-4">
    <p className="text-ash text-xs uppercase tracking-[0.2em]">{k}</p>
    <p className={`font-display text-3xl mt-1 ${tone}`}>{v}</p>
  </div>
);

export default async function TrackRecord() {
  const d = await getRecord();
  const cohort = d?.cohort;
  const hasCohort = cohort?.enough_data;
  const hasEvents = (d?.cases ?? 0) > 0;

  // Never show an empty "receipts" page - it advertises absence.
  if (!hasCohort && !hasEvents) redirect("/methodology");

  const heavy = cohort?.heavy_diluters;
  const light = cohort?.disciplined;

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-10">
      <div className="text-center pt-4">
        <p className="text-assay text-xs uppercase tracking-[0.35em] mb-2">The Receipts</p>
        <h1 className="font-display text-5xl tracking-wide">What dilution actually did.</h1>
        <p className="text-bone/85 text-lg mt-3 max-w-2xl mx-auto">
          Not a highlight reel. Every company we track with filing history is
          included — winners, losers and non-events — computed automatically
          from share counts and end-of-day prices.
        </p>
      </div>

      {hasCohort && (
        <>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="bg-tray border border-hazard rounded-sm p-5">
              <p className="text-hazard text-xs uppercase tracking-[0.3em] mb-1">
                Heavy issuance
              </p>
              <p className="text-ash text-xs mb-3">
                Share count grew 25%+ over ~{cohort.window_months} months ·{" "}
                {heavy.count} companies
              </p>
              <p className="font-display text-5xl text-hazard">
                {heavy.median_price_change_pct > 0 ? "+" : ""}
                {heavy.median_price_change_pct}%
              </p>
              <p className="text-bone/85 text-sm mt-1">median price change</p>
              <p className="text-ash text-xs mt-2">
                {heavy.share_that_fell_pct}% of them fell · median share growth{" "}
                +{heavy.median_share_growth_pct}%
              </p>
            </div>

            <div className="bg-tray border border-oxide rounded-sm p-5">
              <p className="text-oxide text-xs uppercase tracking-[0.3em] mb-1">
                Disciplined issuance
              </p>
              <p className="text-ash text-xs mb-3">
                Share count grew under 10% · {light.count} companies
              </p>
              <p className="font-display text-5xl text-oxide">
                {light.median_price_change_pct > 0 ? "+" : ""}
                {light.median_price_change_pct}%
              </p>
              <p className="text-bone/85 text-sm mt-1">median price change</p>
              <p className="text-ash text-xs mt-2">
                {light.share_that_fell_pct}% of them fell · median share growth{" "}
                +{light.median_share_growth_pct}%
              </p>
            </div>
          </div>

          <div className="bg-tray border border-seam rounded-sm p-5">
            <p className="text-hazard text-xs uppercase tracking-[0.3em] mb-3">
              The hardest hits — heavy issuance, worst outcomes
            </p>
            <div className="space-y-2">
              {cohort.worst_cases.map((c: Record<string, string | number>, i: number) => (
                <div key={i} className="border-b border-seam/60 last:border-0 pb-2 last:pb-0">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <a href={`/ticker/${c.ticker}`} className="font-mono text-assay hover:underline">
                      {c.ticker}
                    </a>
                    <span className="text-bone/85 text-sm">{c.name}</span>
                    <span className="text-hazard font-mono text-sm ml-auto">
                      {c.price_change_pct}%
                    </span>
                  </div>
                  <p className="text-ash text-xs mt-0.5">
                    shares {(Number(c.shares_from) / 1e6).toFixed(1)}M →{" "}
                    {(Number(c.shares_to) / 1e6).toFixed(1)}M (+{c.share_growth_pct}%) · price $
                    {c.price_from} → ${c.price_to} · {c.from_date} to {c.to_date}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {hasEvents && (
        <div className="bg-tray border border-seam rounded-sm p-5">
          <p className="text-ash text-xs uppercase tracking-[0.3em] mb-2">
            Around financing announcements ({d.cases} tracked, {d.window_days}-day window)
          </p>
          <div className="grid sm:grid-cols-3 gap-3 mt-2">
            <Stat k="Median move" v={`${d.median_change_pct > 0 ? "+" : ""}${d.median_change_pct}%`} />
            <Stat k="Fell after" v={`${d.share_that_fell_pct}%`} />
            <Stat k="Fell 20%+" v={`${d.share_that_fell_20plus_pct}%`} />
          </div>
        </div>
      )}

      <div className="bg-tray border border-seam rounded-sm p-5">
        <p className="text-ash text-xs uppercase tracking-[0.3em] mb-2">How this is computed</p>
        <p className="text-bone/85 text-sm leading-relaxed">
          {cohort?.methodology ?? d?.methodology}
        </p>
      </div>

      <div className="bg-tray border border-assay rounded-sm p-6 text-center">
        <p className="font-display text-2xl tracking-wide">This is why the grade matters.</p>
        <p className="text-bone/85 mt-2 max-w-xl mx-auto">
          OreLens flags the companies most likely to need money — before they ask for yours.
        </p>
        <a href="/pricing"
           className="inline-block mt-4 bg-assay text-shale font-display tracking-wide font-semibold text-lg px-7 py-2.5 rounded-sm hover:opacity-90">
          Become a Founding Member →
        </a>
      </div>
    </div>
  );
}
