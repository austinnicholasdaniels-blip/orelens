import type { Metadata } from "next";
import "./globals.css";
import SpotlightFooter from "@/components/SpotlightFooter";
import NavLinks from "@/components/NavLinks";
import PromoBar from "@/components/PromoBar";

export const metadata: Metadata = {
  metadataBase: new URL("https://getorelens.com"),
  title: "OreLens — See dilution before it hits",
  description:
    "The dilution-intelligence terminal for junior mining investors. Dilution grades A\u2013F, the Unlock Calendar, the disclosed-promotion registry, and The Assayer AI \u2014 built from filings, refreshed nightly.",
  openGraph: {
    title: "OreLens — See dilution before it hits",
    description:
      "Dilution grades A\u2013F \u00b7 the Unlock Calendar \u00b7 the promotion registry \u00b7 The Assayer AI. There is no second OreLens.",
    url: "https://getorelens.com",
    siteName: "OreLens",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "OreLens — See dilution before it hits",
    description:
      "Dilution grades A\u2013F \u00b7 the Unlock Calendar \u00b7 the promotion registry \u00b7 The Assayer AI.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <PromoBar />
        <header className="border-b border-seam px-6 py-4 flex items-baseline gap-4">
          <a href="/" className="font-display text-2xl tracking-wide text-assay">ORELENS</a>
          <span className="text-xs text-ash uppercase tracking-widest hidden sm:inline">
            Dilution · Warrants · Drill Results
          </span>
          <nav className="ml-auto flex items-baseline gap-5 text-sm">
            <NavLinks />
          </nav>
        </header>
        <main className="px-6 py-6 max-w-7xl mx-auto">{children}
          <SpotlightFooter /></main>
        <footer className="border-t border-seam mt-14">
          <div className="max-w-7xl mx-auto px-6 py-10 grid gap-8 md:grid-cols-[2fr_1fr_1fr]">
            <div>
              <p className="font-display text-2xl tracking-wide text-assay">ORELENS</p>
              <p className="text-ash text-sm mt-2 leading-relaxed max-w-md">
                The dilution-intelligence terminal for junior mining investors.
                Built from public filings, disclosures, and licensed market
                data, refreshed nightly. There is no second OreLens.
              </p>
            </div>
            <div className="text-sm">
              <p className="text-ash text-xs uppercase tracking-[0.25em] mb-3">Platform</p>
              <div className="space-y-2">
                <a href="/dashboard" className="block text-bone hover:text-assay">The Terminal</a>
                <a href="/methodology" className="block text-bone hover:text-assay">How Grades Work</a>
                <a href="/training" className="block text-bone hover:text-assay">Free Training</a>
                <a href="/pricing" className="block text-bone hover:text-assay">Pricing</a>
              </div>
            </div>
            <div className="text-sm">
              <p className="text-ash text-xs uppercase tracking-[0.25em] mb-3">Company</p>
              <div className="space-y-2">
                <a href="/contact" className="block text-bone hover:text-assay">Contact</a>
                <a href="/digest" className="block text-bone hover:text-assay">Weekly Digest</a>
                <a href="/assayer" className="block text-bone hover:text-assay">The Assayer</a>
              </div>
            </div>
          </div>
          <div className="border-t border-seam/60">
            <p className="max-w-7xl mx-auto px-6 py-4 text-ash text-xs leading-relaxed">
              OreLens is a research platform, not investment advice. Nothing on
              this site is a recommendation to buy or sell any security. Grades
              and scores are computed from public filings, disclosures, and
              licensed market data; they can be wrong, late, or incomplete -
              verify independently before acting. Subscriptions renew annually
              via Stripe and can be cancelled anytime.
              &nbsp;\u00b7&nbsp; \u00a9 2026 OreLens \u00b7 Junior Mining Media Group
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
