// The ask, placed at the bottom of every free page. Honest urgency only:
// founding pricing genuinely rises at launch.
export default function ConversionBand({ context }: { context: string }) {
  return (
    <section className="mt-12 bg-tray border border-assay rounded-sm p-8 text-center">
      <p className="text-ash text-xs uppercase tracking-[0.3em] mb-2">Founding Membership</p>
      <h3 className="font-display text-3xl tracking-wide">
        {context}
      </h3>
      <p className="text-bone/85 max-w-xl mx-auto mt-3 text-lg">
        Every scanner, dilution grades on 200+ miners, the Unlock Calendar,
        the promotion registry, and The Assayer AI - for less than the cost
        of one bad fill.
      </p>
      <p className="mt-4">
        <span className="text-ash line-through mr-2">$725/yr</span>
        <span className="font-display text-4xl">$97.99</span>
        <span className="text-ash">/year</span>
        <span className="text-oxide text-sm ml-3">founding price - locks in for life</span>
      </p>
      <div className="flex items-center justify-center gap-4 mt-5">
        <a href="/pricing"
           className="bg-assay text-shale font-display tracking-wide font-semibold text-lg px-8 py-3 rounded-sm hover:opacity-90">
          Become a Founding Member &rarr;
        </a>
      </div>
      <p className="text-ash text-xs mt-3">30-second Stripe checkout &middot; cancel anytime &middot; price rises to $725/yr when the launch window closes</p>
    </section>
  );
}
