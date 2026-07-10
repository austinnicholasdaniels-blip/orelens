"use client";
import { useEffect } from "react";

export default function Welcome() {
  useEffect(() => {
    const yr = 365 * 24 * 3600;
    document.cookie = `orelens_beta=1; max-age=${yr}; path=/; SameSite=Lax`;
    document.cookie = `orelens_member=1; max-age=${yr}; path=/; SameSite=Lax`;
  }, []);

  return (
    <div className="max-w-xl mx-auto text-center pt-20 space-y-6">
      <span className="bg-assay text-shale text-[10px] font-bold tracking-[0.25em] px-2.5 py-1 rounded-sm">
        FOUNDING MEMBER
      </span>
      <h1 className="font-display text-5xl tracking-wide">Welcome aboard.</h1>
      <p className="text-bone/85">
        Your founding membership is active and this browser is unlocked.
        Your receipt is in your inbox from Stripe.
      </p>
      <a href="/dashboard"
         className="inline-block bg-assay text-shale font-display tracking-wide font-semibold px-8 py-3 rounded-sm hover:opacity-90">
        Open the Terminal &rarr;
      </a>
      <p className="text-ash text-xs">
        New device? Just open this page again from your receipt link.
      </p>
    </div>
  );
}
