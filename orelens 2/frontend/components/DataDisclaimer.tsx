/**
 * Contextual disclaimers. Deliberately specific per surface - a generic
 * "not advice" line everywhere becomes wallpaper. Each variant names the
 * actual limitation of the thing the member is looking at.
 */
type Variant = "scanner" | "assayer" | "ticker" | "events" | "digest";

const COPY: Record<Variant, { lead: string; body: string }> = {
  scanner: {
    lead: "How to read this",
    body:
      "Computed automatically from public filings, disclosures, and licensed end-of-day market data, refreshed nightly. Figures can be late, incomplete, or wrong - filings lag reality and small issuers disclose unevenly. Verify against original filings before acting. Research tool, not investment advice.",
  },
  assayer: {
    lead: "Before you act on this",
    body:
      "The Assayer is an AI research tool. It can be wrong. Its reasoning is only as good as the underlying data, and it may misjudge context even when the figures are right. Every event it cites carries a source - click through and confirm it. Nothing here is a recommendation to buy or sell any security, and no output should be treated as a substitute for your own due diligence or a licensed advisor.",
  },
  ticker: {
    lead: "Data notes",
    body:
      "Capital-structure figures come from the most recent filings we hold; the as-of date is shown with each. Grades are mechanical outputs, not opinions on value. Verify against the issuer's own filings before acting. Research tool, not investment advice.",
  },
  events: {
    lead: "About these events",
    body:
      "Financings and promotions are parsed automatically from newswire releases. Each row links to the source headline it came from - if a row looks wrong, click the source, then tell us and we'll correct it.",
  },
  digest: {
    lead: "About this digest",
    body:
      "Generated from the same nightly data as the terminal. Figures can be late or incomplete. Research only - not investment advice.",
  },
};

export default function DataDisclaimer({
  variant,
  className = "",
}: {
  variant: Variant;
  className?: string;
}) {
  const c = COPY[variant];
  return (
    <div className={`border-t border-seam mt-6 pt-3 ${className}`}>
      <p className="text-ash text-[11px] leading-relaxed">
        <span className="uppercase tracking-[0.2em] text-ash/80 mr-2">
          {c.lead}
        </span>
        {c.body}
      </p>
    </div>
  );
}
