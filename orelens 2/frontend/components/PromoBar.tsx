"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function PromoBar() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (document.cookie.includes("orelens_promo_hide=1")) return;
    if (window.location.pathname === "/training") return;
    fetch(`${API}/api/site-config`)
      .then((r) => r.json())
      .then((d) => { if (d.training_video_url) setShow(true); })
      .catch(() => {});
  }, []);

  if (!show) return null;

  const dismiss = () => {
    document.cookie = "orelens_promo_hide=1; max-age=86400; path=/";
    setShow(false);
  };

  return (
    <div className="bg-assay/12 border-b border-assay/50">
      <div className="max-w-7xl mx-auto px-6 py-2 flex items-center gap-3 text-sm">
        <span className="bg-assay text-shale text-[10px] font-bold tracking-[0.2em] px-1.5 py-0.5 rounded-sm">
          FREE TRAINING
        </span>
        <a href="/training" className="text-bone hover:text-assay font-semibold">
          Watch: how to spot a dilution trap before it hits &rarr;
        </a>
        <button onClick={dismiss} aria-label="Dismiss"
          className="ml-auto text-ash hover:text-bone text-lg leading-none">&times;</button>
      </div>
    </div>
  );
}
