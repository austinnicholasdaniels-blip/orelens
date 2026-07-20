import type { Metadata } from "next";
import TickerClient from "./TickerClient";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://orelens-api.onrender.com";
const SITE = "https://getorelens.com";

async function fetchPublic(symbol: string) {
  try {
    const r = await fetch(`${API}/api/public/ticker/${symbol}`, {
      next: { revalidate: 3600 },
    });
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: { symbol: string };
}): Promise<Metadata> {
  const t = params.symbol.toUpperCase();
  const d = await fetchPublic(t);
  if (!d) {
    return {
      title: `${t} — Dilution & Share Structure | OreLens`,
      description: `Dilution grade, cash runway, warrant overhang, and share-structure history for ${t}, from public filings.`,
    };
  }
  const grade = d.grade ? `Dilution grade ${d.grade}. ` : "";
  const title = `${d.name} (${t}) Dilution, Cash Runway & Share Structure | OreLens`;
  const description = `${grade}${d.name} (${d.exchange}: ${t}) — ${d.commodity} ${d.jurisdiction ? "in " + d.jurisdiction : ""}. Cash runway, warrant overhang, financing unlocks, and share-count history from public filings. ${d.shares_outstanding ? (d.shares_outstanding / 1e6).toFixed(0) + "M shares outstanding." : ""}`.trim();
  return {
    title,
    description,
    alternates: { canonical: `${SITE}/ticker/${t}` },
    openGraph: {
      title,
      description,
      url: `${SITE}/ticker/${t}`,
      siteName: "OreLens",
      images: [{ url: "/og.png", width: 1200, height: 630 }],
      type: "website",
    },
    twitter: { card: "summary_large_image", title, description, images: ["/og.png"] },
  };
}

export default async function TickerPage({
  params,
}: {
  params: { symbol: string };
}) {
  const t = params.symbol.toUpperCase();
  const d = await fetchPublic(t);

  // JSON-LD structured data for rich search results
  const jsonLd = d
    ? {
        "@context": "https://schema.org",
        "@type": "Corporation",
        name: d.name,
        tickerSymbol: t,
        description: `${d.commodity} company${d.jurisdiction ? " in " + d.jurisdiction : ""}, tracked on OreLens for dilution risk and share structure.`,
      }
    : null;

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      )}

      {/* Public, crawlable SEO summary - real content for search engines and
          a hook for searchers. The full interactive terminal is gated below. */}
      {d && (
        <section className="mb-8">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="font-display text-4xl tracking-wide">
              {d.name}
              <span className="text-ash text-2xl ml-2">
                {d.exchange}: {t}
              </span>
            </h1>
            {d.grade && (
              <span className="border border-assay text-assay rounded-sm px-2 py-0.5 font-display text-xl">
                {d.grade}
              </span>
            )}
          </div>
          <p className="text-ash mt-1">
            {d.commodity}
            {d.jurisdiction ? ` · ${d.jurisdiction}` : ""}
          </p>

          <div className="grid sm:grid-cols-3 gap-3 mt-5">
            {[
              ["Dilution Grade", d.grade ?? "—"],
              ["Shares Outstanding", d.shares_outstanding ? `${(d.shares_outstanding / 1e6).toFixed(1)}M` : "—"],
              ["Cash Runway", d.runway_m == null ? "n/a" : d.runway_m >= 120 ? "120+ mo" : `${d.runway_m} mo`],
              ["1-Yr Share Growth", d.share_growth_1y != null ? `${d.share_growth_1y > 0 ? "+" : ""}${d.share_growth_1y}%` : "—"],
              ["Latest Close", d.latest_close != null ? `$${d.latest_close}` : "—"],
              ["Cash on Hand", d.cash != null ? `$${(d.cash / 1e6).toFixed(1)}M` : "—"],
            ].map(([k, v]) => (
              <div key={k as string} className="bg-tray border border-seam rounded-sm p-3">
                <p className="text-ash text-xs">{k}</p>
                <p className="font-mono text-lg mt-0.5">{v}</p>
              </div>
            ))}
          </div>

          <p className="text-bone/85 mt-5 leading-relaxed max-w-3xl">
            {d.name} ({d.exchange}: {t}) is a {d.commodity.toLowerCase()} company
            {d.jurisdiction ? ` operating in ${d.jurisdiction}` : ""}. OreLens
            tracks its dilution risk, cash runway, warrant overhang, private-placement
            unlocks, and full share-count history — computed from public filings and
            refreshed nightly. {d.grade ? `Its current dilution grade is ${d.grade}.` : ""}{" "}
            The full interactive terminal — charts, the unlock calendar, financing
            history, and drill results — is available to members below.
          </p>
        </section>
      )}

      {/* The gated interactive terminal */}
      <TickerClient params={params} />
    </>
  );
}
