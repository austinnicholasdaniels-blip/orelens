import type { Metadata } from "next";
import "./globals.css";
import SpotlightFooter from "@/components/SpotlightFooter";

export const metadata: Metadata = {
  title: "OreLens — Dilution & Drill Intelligence",
  description: "Junior mining dilution risk grades, warrant overhangs, and drill-result scanners",
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
        <header className="border-b border-seam px-6 py-4 flex items-baseline gap-4">
          <a href="/" className="font-display text-2xl tracking-wide text-assay">ORELENS</a>
          <span className="text-xs text-ash uppercase tracking-widest hidden sm:inline">
            Dilution · Warrants · Drill Results
          </span>
          <nav className="ml-auto flex items-baseline gap-5 text-sm">
            <a href="/dashboard" className="text-bone hover:text-assay">Scanners</a>
            <a href="/news" className="text-bone hover:text-assay">News</a>
            <a href="/research/promotions" className="text-bone hover:text-assay">Research</a>
            <a href="/digest" className="text-bone hover:text-assay">Digest</a>
            <a href="/assayer" className="text-bone hover:text-assay">Assayer</a>
            <a href="/pricing" className="text-assay hover:opacity-80">Pricing</a>
            <a href="/login" className="text-bone hover:text-assay">Log in</a>
            <span className="text-xs text-ash font-mono hidden md:inline">nightly sync 23:00 EST</span>
          </nav>
        </header>
        <main className="px-6 py-6 max-w-7xl mx-auto">{children}
          <SpotlightFooter /></main>
      </body>
    </html>
  );
}
