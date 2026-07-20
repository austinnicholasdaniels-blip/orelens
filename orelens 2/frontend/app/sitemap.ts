import type { MetadataRoute } from "next";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://orelens-api.onrender.com";
const SITE = "https://getorelens.com";

export const revalidate = 86400; // rebuild daily

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticPages = [
    "", "/pricing", "/training", "/methodology", "/contact", "/digest",
    "/research/promotions",
  ].map((p) => ({
    url: `${SITE}${p}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: p === "" ? 1 : 0.7,
  }));

  let tickerPages: MetadataRoute.Sitemap = [];
  try {
    const rows = await fetch(`${API}/api/scanners/all-stocks`, {
      next: { revalidate: 86400 },
    }).then((r) => r.json());
    if (Array.isArray(rows)) {
      tickerPages = rows.map((r: { ticker: string }) => ({
        url: `${SITE}/ticker/${r.ticker}`,
        lastModified: new Date(),
        changeFrequency: "daily" as const,
        priority: 0.6,
      }));
    }
  } catch {
    /* sitemap still valid with static pages if the API is briefly down */
  }
  return [...staticPages, ...tickerPages];
}
