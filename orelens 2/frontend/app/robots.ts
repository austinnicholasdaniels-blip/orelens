import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // keep member-only + auth surfaces out of the index
      disallow: ["/welcome", "/login", "/api/"],
    },
    sitemap: "https://getorelens.com/sitemap.xml",
  };
}
