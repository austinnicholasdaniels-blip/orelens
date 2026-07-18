export const metadata = { title: "Contact — OreLens" };

export default function Contact() {
  return (
    <div className="max-w-2xl mx-auto space-y-6 pb-10">
      <div className="text-center pt-4">
        <h1 className="font-display text-5xl tracking-wide">Contact</h1>
        <p className="text-bone/85 text-lg mt-3">
          A real person reads every message.
        </p>
      </div>

      <div className="bg-tray border border-seam rounded-sm p-7 space-y-5">
        <div>
          <p className="text-assay text-xs uppercase tracking-[0.3em] mb-1">Members & general</p>
          <a href="mailto:contact@getorelens.com" className="font-mono text-xl text-bone hover:text-assay">
            contact@getorelens.com
          </a>
          <p className="text-ash text-sm mt-1">Login trouble, billing, data corrections, feature requests.</p>
        </div>
        <div className="border-t border-seam pt-5">
          <p className="text-assay text-xs uppercase tracking-[0.3em] mb-1">Advertising & partnerships</p>
          <a href="mailto:advertise@getorelens.com" className="font-mono text-xl text-bone hover:text-assay">
            advertise@getorelens.com
          </a>
          <p className="text-ash text-sm mt-1">Spotlight placements and the weekly digest.</p>
        </div>
        <div className="border-t border-seam pt-5">
          <p className="text-assay text-xs uppercase tracking-[0.3em] mb-1">Spotted a data error?</p>
          <p className="text-bone/90 text-sm leading-relaxed">
            Tell us the ticker and what&apos;s wrong. Corrections usually ship the
            same day, and the nightly rebuild carries them through every
            scanner and grade automatically.
          </p>
        </div>
      </div>

      <p className="text-ash text-xs text-center">
        OreLens is a research platform, not investment advice.
      </p>
    </div>
  );
}
