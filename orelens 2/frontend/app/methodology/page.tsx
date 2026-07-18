export const metadata = { title: "How Grades Work — OreLens" };

const Section = ({ k, t, children }: { k: string; t: string; children: React.ReactNode }) => (
  <section className="bg-tray border border-seam rounded-sm p-7">
    <p className="text-assay text-xs uppercase tracking-[0.3em] mb-1.5">{k}</p>
    <h2 className="font-display text-3xl tracking-wide mb-3">{t}</h2>
    <div className="text-bone/90 leading-relaxed space-y-3">{children}</div>
  </section>
);

export default function Methodology() {
  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-10">
      <div className="text-center pt-4 pb-2">
        <p className="text-ash text-xs uppercase tracking-[0.35em] mb-2">We show our math</p>
        <h1 className="font-display text-5xl tracking-wide">How the grades work.</h1>
        <p className="text-bone/85 text-lg mt-3 max-w-xl mx-auto">
          Every number on OreLens traces back to a filing, a disclosure, or
          licensed market data. Here is exactly how the machine thinks.
        </p>
      </div>

      <Section k="01" t="Where the data comes from">
        <p>
          Public regulatory filings and financial statements, exchange
          disclosures, company press releases, and licensed end-of-day market
          data. The entire universe is re-synced every night - prices,
          filings, financings, promotions, and grades are recomputed
          automatically. Every ticker page shows the as-of date of its data.
        </p>
      </Section>

      <Section k="02" t="The dilution grade, A to F">
        <p>
          The grade answers one question: <span className="text-assay">how
          likely is this company to need your money soon, and at what cost to
          your position?</span> It is recomputed nightly from four inputs:
        </p>
        <p>
          <span className="text-bone font-semibold">Adjusted runway</span> -
          cash on hand, minus the cost of planned drilling, divided by monthly
          burn. Under 1 month grades F; under 3 months D; 3-6 months C; 6-12
          months B. An A requires 12+ months of funding (or in-the-money
          warrants that can cover a full year) <em>and</em> a modest warrant
          overhang.
        </p>
        <p>
          <span className="text-bone font-semibold">Warrant overhang</span> -
          total warrants outstanding as a share of float. Above 15% caps a
          company at B regardless of treasury strength.
        </p>
        <p>
          <span className="text-bone font-semibold">Unlock pressure</span> -
          private-placement paper coming free-trading within the next seven
          days. More than 25% of float unlocking in a week grades F on the
          spot, whatever the balance sheet says.
        </p>
        <p>
          <span className="text-bone font-semibold">Funding coverage</span> -
          whether in-the-money warrant exercises could realistically fund the
          next twelve months of burn plus drilling.
        </p>
      </Section>

      <Section k="03" t="How burn is measured (and when we say we don't know)">
        <p>
          Monthly burn follows an evidence ladder, and each rung is labeled in
          the grade rationale:
        </p>
        <p>
          <span className="text-oxide font-semibold">Stated</span> - derived
          from the company's own reported cash flow.{" "}
          <span className="text-oxide font-semibold">Estimated</span> - when
          reported figures are missing but the treasury is visibly shrinking
          across quarters, we use the median decline and say so.{" "}
          <span className="text-oxide font-semibold">Self-funded</span> - only
          claimed when multiple filings show cash holding or growing.{" "}
          <span className="text-oxide font-semibold">Unknown</span> - when
          filings are too thin to measure, runway shows{" "}
          <span className="font-mono">n/a</span> and the grade leans on
          overhang and unlock risk only. Missing data is treated as missing -
          never as zero.
        </p>
      </Section>

      <Section k="04" t="The Unlock Calendar & Promotion Registry">
        <p>
          Private placements are tracked from announcement to close; the
          four-month hold is projected from the closing date, giving the exact
          day the paper free-trades and the dollar amount behind it. The
          promotion registry records <em>disclosed</em> investor-awareness and
          IR engagements - who is being promoted and, where disclosed, how
          much was paid. Legal, disclosed, and almost never read. We read it.
        </p>
      </Section>

      <Section k="05" t="The Assayer">
        <p>
          The Assayer grades a member&apos;s trade idea with AI that reads this
          platform&apos;s own database while it reasons: runway against your
          stated timeline, raises announced but not yet closed, promotions
          running, paper unlocking inside your holding window. Platform data
          is authoritative for figures; the model&apos;s broader knowledge is used
          for company identity. It grades the quality of your reasoning - it
          does not tell you to buy or sell anything.
        </p>
      </Section>

      <Section k="06" t="What the grades are not">
        <p>
          Grades are not price predictions, not buy/sell signals, and not
          investment advice. They measure one dimension - capital-structure
          risk - computed mechanically from public information. They can be
          wrong, late, or incomplete: filings lag reality, and small
          companies disclose unevenly. If you find an error, tell us at{" "}
          <a href="/contact" className="text-assay hover:underline">contact</a>{" "}
          - corrections ship fast, and the nightly rebuild picks them up
          automatically.
        </p>
      </Section>
    </div>
  );
}
