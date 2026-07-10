"use client";
import { useEffect, useState } from "react";

const MEMBER_COOKIE = "orelens_member";

function hasCookie(name: string): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${name}=`));
}

export default function BetaGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "locked" | "open">("checking");

  useEffect(() => {
    setState(hasCookie(MEMBER_COOKIE) ? "open" : "locked");
  }, []);

  if (state === "open") return <>{children}</>;
  if (state === "checking") return null;

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div className="max-w-lg w-full bg-tray border border-assay rounded-sm p-8 text-center relative">
        <span className="absolute top-4 right-4 bg-assay text-shale text-[10px] font-bold tracking-[0.2em] px-2 py-1 rounded-sm">
          MEMBERS ONLY
        </span>
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-3">OreLens Terminal</p>
        <h2 className="font-display text-4xl tracking-wide">
          The full terminal is for members.
        </h2>
        <p className="text-bone/85 mt-4">
          Every scanner, the Unlock Calendar, dilution grades on 200+ mining
          companies, and the promotion registry - refreshed nightly.
        </p>
        <p className="mt-5">
          <span className="font-display text-3xl">$99.99</span>
          <span className="text-ash">/year</span>
        </p>
        <p className="text-oxide text-sm mt-1">
          Founding-member launch price &middot; $725/year after the launch window
        </p>
        <div className="text-left max-w-sm mx-auto mt-5 space-y-1.5">
          {["All 11 scanners + dilution grades on 200+ miners",
            "Unlock Calendar + disclosed promotion registry",
            "The Assayer - AI grading for your trade ideas"].map((f) => (
            <p key={f} className="text-sm text-bone/90">
              <span className="text-oxide mr-2">{"\u2713"}</span>{f}
            </p>
          ))}
        </div>
        <div className="flex flex-col sm:flex-row gap-3 justify-center mt-6">
          <a href="/pricing"
             className="bg-assay text-shale font-display tracking-wide font-semibold px-7 py-3 rounded-sm hover:opacity-90">
            Become a Member &rarr;
          </a>
          <a href="/login"
             className="border border-seam text-bone px-7 py-3 rounded-sm hover:border-assay hover:text-assay">
            Member log in
          </a>
        </div>
        <p className="text-ash text-xs mt-5">
          30-second Stripe checkout &middot; cancel anytime &middot; founding price
          rises to $725/yr at launch. Research platform, not investment advice.
        </p>
      </div>
    </div>
  );
}
