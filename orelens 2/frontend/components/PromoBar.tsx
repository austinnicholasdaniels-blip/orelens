"use client";
import { useEffect, useState } from "react";

export default function PromoBar() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (document.cookie.includes("orelens_promo_hide=1")) return;
    if (window.location.pathname === "/training") return;
    setShow(true);
  }, []);

  if (!show) return null;

  const dismiss = () => {
    document.cookie = "orelens_promo_hide=1; max-age=86400; path=/";
    setShow(false);
  };

  return (
    <a href="/training" className="block promo-shimmer bg-assay/12 border-b border-assay/60 hover:bg-assay/20 transition-colors relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 py-2.5 flex items-center gap-3 text-sm">
        <span className="promo-pulse bg-assay text-shale text-[10px] font-bold tracking-[0.2em] px-2 py-1 rounded-sm whitespace-nowrap">
          FREE TRAINING
        </span>
        <span className="text-bone font-semibold">
          Watch: how to spot a dilution trap before it hits
          <span className="text-assay ml-2 promo-arrow inline-block">&rarr;</span>
        </span>
        <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); dismiss(); }}
          aria-label="Dismiss"
          className="ml-auto text-ash hover:text-bone text-lg leading-none relative z-10">&times;</button>
      </div>
    </a>
  );
}
