import { redirect } from "next/navigation";

export const metadata = {
  title: "What Dilution Did to Holders | OreLens Track Record",
  description:
    "Real companies, real dates. What happened to shareholders from the first dilution announcement onward — computed from filings, one entry per company.",
};

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://orelens-api.onrender.com";

async function getRecord() {
  try {
    const r = await fetch(`${API}/api/track-record`, { next: { revalidate: 3600 } });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

export default async function TrackRecord() {
  const d = await getRecord();
  const dd = d?.drawdown;
  const cohort = d?.cohort;
  const hasDD = dd?.enough_data;
  const hasCohort = cohort?.enough_data;

  // never show an empty "receipts" page
  if (!hasDD && !hasCohort) redirect("/methodology");

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-10">
      <div className="text-center pt-4">
        <p className="text-hazard text-xs uppercase tracking-[0.35em] mb-2">
          The Receipts
        </p>
        <h1 className="font-display text-5xl tracking-wide leading-tight">
          They announced a raise.<br />
          <span className="text-hazard">Then this happened.</span>
        </h1>
        <p className="text-bone/85 text-lg mt-4 max-w-2xl mx-auto leading-relaxed">
          Every company below issued a financing announcement. Holders who
          weren&apos;t watching found out the way most people do — by opening
          their account and seeing red. One entry per company, measured from
          the first announcement, computed from filings and end-of-day prices.
        </p>
      </div>

      {hasDD && (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-tray border border-hazard rounded-sm p-4">
              <p className="text-ash text-xs uppercase tracking-[0.2em]">Median drawdown</p>
              <p className="font-display text-4xl mt-1 text-hazard">
                {dd.median_max_drawdown_pct}%
              </p>
              <p className="text-ash text-xs mt-1">after the first raise</p>
            </div>
            <div className="bg-tray border border-seam rounded-sm p-4">
              <p className="text-ash text-xs uppercase tracking-[0.2em]">Fell 20%+</p>
              <p className="font-display text-4xl mt-1">{dd.share_down_20plus_pct}%</p>
              <p className="text-ash text-xs mt-1">of these companies</p>
            </div>
            <div className="bg-tray border border-seam rounded-sm p-4">
              <p className="text-ash text-xs uppercase tracking-[0.2em]">Fell 40%+</p>
              <p className="font-display text-4xl mt-1">{dd.share_down_40plus_pct}%</p>
              <p className="text-ash text-xs mt-1">of these companies</p>
            </div>
            <div className="bg-tray border border-seam rounded-sm p-4">
              <p className="text-ash text-xs uppercase tracking-[0.2em]">Still underwater</p>
              <p className="font-display text-4xl mt-1">{dd.share_still_below_pct}%</p>
              <p className="text-ash text-xs mt-1">trade below the announcement</p>
            </div>
          </div>

          <div className="bg-tray border border-hazard rounded-sm p-5">
            <p className="text-hazard text-xs uppercase tracking-[0.3em] mb-1">
              Company by company
            </p>
            <p className="text-ash text-xs mb-4">
              Price on the day of the first announcement → the lowest it traded
              afterward. &ldquo;Today&rdquo; shows whether it ever recovered.
            </p>
            <div className="space-y-3">
              {dd.cases.map((c: Record<string, string | number>, i: number) => (
                <div key={i} className="border-b border-seam/60 last:border-0 pb-3 last:pb-0">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <a href={`/ticker/${c.ticker}`} className="font-mono text-assay hover:underline text-lg">
                      {c.ticker}
                    </a>
                    <span className="text-bone/90 text-sm">{c.name}</span>
                    <span className="font-display text-2xl text-hazard ml-auto">
                      {c.max_drawdown_pct}%
                    </span>
                  </div>
                  <p className="text-bone/80 text-sm mt-1">
                    <span className="text-ash">Announced {c.announced}:</span> $
                    {c.anchor_price} → <span className="text-hazard">${c.trough_price}</span>{" "}
                    <span className="text-ash">
                      (bottom {c.trough_day}, {c.days_to_trough} days later)
                    </span>
                  </p>
                  <p className="text-ash text-xs mt-0.5">
                    Today ${c.price_today} ·{" "}
                    <span className={Number(c.change_since_pct) < 0 ? "text-hazard" : "text-oxide"}>
                      {Number(c.change_since_pct) > 0 ? "+" : ""}
                      {c.change_since_pct}% vs the announcement
                    </span>
                    {c.source && (
                      <>
                        {" · "}
                        <a href={c.source as string} target="_blank" rel="noopener noreferrer"
                           className="text-assay hover:underline">source ↗</a>
                      </>
                    )}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-tray border border-assay rounded-sm p-6">
            <p className="font-display text-3xl tracking-wide text-center">
              Every one of these was visible in advance.
            </p>
            <p className="text-bone/90 mt-3 leading-relaxed text-center max-w-2xl mx-auto">
              Not one of these companies raised money out of nowhere. The cash
              was draining. The runway was shrinking. The warrants were
              stacking up. It was all sitting in public filings — the kind
              nobody reads until it&apos;s too late.{" "}
              <span className="text-assay">
                OreLens reads them every night and grades every company A to F,
                so you see the risk while you can still act on it.
              </span>
            </p>
            <p className="text-bone/85 mt-3 text-center">
              The only question that matters:{" "}
              <span className="text-hazard">is one of these in your account right now?</span>
            </p>
            <div className="text-center mt-5">
              <a href="/pricing"
                 className="inline-block bg-assay text-shale font-display tracking-wide font-semibold text-lg px-8 py-3 rounded-sm hover:opacity-90">
                Check your positions — $97.99/yr →
              </a>
              <p className="text-ash text-xs mt-2">
                Founding price, locks in for life · one bad fill costs more than a decade of this
              </p>
            </div>
          </div>
        </>
      )}

      {hasCohort && (
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="bg-tray border border-hazard rounded-sm p-5">
            <p className="text-hazard text-xs uppercase tracking-[0.3em] mb-1">Heavy issuance</p>
            <p className="text-ash text-xs mb-3">
              Share count grew 25%+ · {cohort.heavy_diluters.count} companies
            </p>
            <p className="font-display text-4xl text-hazard">
              {cohort.heavy_diluters.median_price_change_pct > 0 ? "+" : ""}
              {cohort.heavy_diluters.median_price_change_pct}%
            </p>
            <p className="text-bone/85 text-sm mt-1">median price change</p>
          </div>
          <div className="bg-tray border border-oxide rounded-sm p-5">
            <p className="text-oxide text-xs uppercase tracking-[0.3em] mb-1">Disciplined issuance</p>
            <p className="text-ash text-xs mb-3">
              Share count grew under 10% · {cohort.disciplined.count} companies
            </p>
            <p className="font-display text-4xl text-oxide">
              {cohort.disciplined.median_price_change_pct > 0 ? "+" : ""}
              {cohort.disciplined.median_price_change_pct}%
            </p>
            <p className="text-bone/85 text-sm mt-1">median price change</p>
          </div>
        </div>
      )}

      <div className="bg-tray border border-seam rounded-sm p-5">
        <p className="text-ash text-xs uppercase tracking-[0.3em] mb-2">How this is computed</p>
        <p className="text-bone/85 text-sm leading-relaxed">
          {dd?.methodology ?? cohort?.methodology}
        </p>
      </div>
    </div>
  );
}
