export const metadata = {
  title: "Track Record — What Dilution Actually Did | OreLens",
  description:
    "Every financing OreLens tracked, and what happened to the share price around it. Computed from our own stored data — winners, losers and non-events included.",
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

export default async function TrackRecord() {
  const d = await getRecord();

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-10">
      <div className="text-center pt-4">
        <p className="text-assay text-xs uppercase tracking-[0.35em] mb-2">
          The Receipts
        </p>
        <h1 className="font-display text-5xl tracking-wide">
          What dilution actually did.
        </h1>
        <p className="text-bone/85 text-lg mt-3 max-w-2xl mx-auto">
          Not a highlight reel. This is every financing OreLens tracked, with
          the share price before and after — computed automatically from our
          own stored data, winners and non-events included.
        </p>
      </div>

      {(!d || d.cases === 0) && (
        <div className="bg-tray border border-seam rounded-sm p-8 text-center">
          <p className="font-display text-2xl tracking-wide">
            The record is still building.
          </p>
          <p className="text-ash mt-2 max-w-xl mx-auto">
            {d?.note ??
              "We publish this page from computed history rather than selected examples, so it stays empty until there is enough overlapping financing and price data to be honest about."}
          </p>
        </div>
      )}

      {d && d.cases > 0 && (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              ["Financings measured", d.cases],
              ["Median move", `${d.median_change_pct > 0 ? "+" : ""}${d.median_change_pct}%`],
              ["Fell after announcement", `${d.share_that_fell_pct}%`],
              ["Fell 20%+", `${d.share_that_fell_20plus_pct}%`],
            ].map(([k, v]) => (
              <div key={k as string} className="bg-tray border border-seam rounded-sm p-4">
                <p className="text-ash text-xs uppercase tracking-[0.2em]">{k}</p>
                <p className="font-display text-3xl mt-1">{v}</p>
              </div>
            ))}
          </div>

          <div className="bg-tray border border-hazard rounded-sm p-5">
            <p className="text-hazard text-xs uppercase tracking-[0.3em] mb-3">
              The hardest hits
            </p>
            <div className="space-y-2">
              {d.worst_cases.map((c: Record<string, string | number>, i: number) => (
                <div key={i} className="border-b border-seam/60 last:border-0 pb-2 last:pb-0">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <a href={`/ticker/${c.ticker}`} className="font-mono text-assay hover:underline">
                      {c.ticker}
                    </a>
                    <span className="text-bone/85 text-sm">{c.name}</span>
                    <span className="text-ash text-xs">{c.announced}</span>
                    <span className="font-mono text-hazard ml-auto">
                      {c.change_pct}%
                    </span>
                  </div>
                  <p className="text-ash text-xs mt-0.5">
                    ${c.price_before} → ${c.price_after} ·{" "}
                    {c.source ? (
                      <a href={c.source as string} target="_blank" rel="noopener noreferrer"
                         className="text-assay hover:underline">
                        source ↗
                      </a>
                    ) : (
                      "no source link"
                    )}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-tray border border-seam rounded-sm p-5">
            <p className="text-ash text-xs uppercase tracking-[0.3em] mb-2">
              How this is computed
            </p>
            <p className="text-bone/85 text-sm leading-relaxed">{d.methodology}</p>
          </div>
        </>
      )}

      <div className="bg-tray border border-assay rounded-sm p-6 text-center">
        <p className="font-display text-2xl tracking-wide">
          This is why the grade matters.
        </p>
        <p className="text-bone/85 mt-2 max-w-xl mx-auto">
          OreLens flags the companies most likely to need money — before they
          ask for yours.
        </p>
        <a href="/pricing"
           className="inline-block mt-4 bg-assay text-shale font-display tracking-wide font-semibold text-lg px-7 py-2.5 rounded-sm hover:opacity-90">
          Become a Founding Member →
        </a>
      </div>
    </div>
  );
}
