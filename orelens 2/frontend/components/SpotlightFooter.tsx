"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const HIDE_COOKIE = "orelens_spot_hide";
const WL_COOKIE = "orelens_watchlist";

function getCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.split(";").find((c) => c.trim().startsWith(`${name}=`));
  return m ? decodeURIComponent(m.split("=")[1]) : "";
}

export function getWatchlist(): string[] {
  return getCookie(WL_COOKIE).split(",").filter(Boolean);
}

export function setWatchlist(list: string[]) {
  document.cookie = `${WL_COOKIE}=${encodeURIComponent(list.join(","))}; max-age=${365 * 24 * 3600}; path=/; SameSite=Lax`;
}

export default function SpotlightFooter() {
  const [spot, setSpot] = useState<Record<string, any> | null>(null);
  const [hidden, setHidden] = useState(true);
  const [watched, setWatched] = useState(false);

  useEffect(() => {
    if (getCookie(HIDE_COOKIE)) return;
    fetch(`${API}/api/spotlight`)
      .then((r) => r.json())
      .then((d) => {
        if (d?.active) {
          setSpot(d);
          setHidden(false);
          setWatched(getWatchlist().includes(d.ticker));
        }
      })
      .catch(() => {});
  }, []);

  if (hidden || !spot) return null;

  const addToWatchlist = () => {
    const wl = getWatchlist();
    if (!wl.includes(spot.ticker)) setWatchlist([...wl, spot.ticker]);
    setWatched(true);
  };

  const dismiss = () => {
    document.cookie = `${HIDE_COOKIE}=1; max-age=86400; path=/; SameSite=Lax`;
    setHidden(true);
  };

  return (
    <div className="fixed bottom-0 inset-x-0 z-50 px-3 pb-3">
      <div className="max-w-5xl mx-auto bg-tray border border-assay rounded-sm shadow-2xl px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="bg-assay text-shale text-[10px] font-bold tracking-[0.2em] px-2 py-0.5 rounded-sm">
          SPOTLIGHT
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-display text-lg tracking-wide leading-tight truncate">
            {spot.headline}
          </p>
          <p className="text-ash text-xs truncate">{spot.blurb}</p>
        </div>
        <div className="flex items-center gap-2">
          <a href={`/ticker/${spot.ticker}`}
             className="bg-assay text-shale font-semibold text-sm px-4 py-1.5 rounded-sm font-display tracking-wide hover:opacity-90 whitespace-nowrap">
            View the Story &rarr;
          </a>
          <button onClick={addToWatchlist} disabled={watched}
            className="border border-assay text-assay text-sm px-3 py-1.5 rounded-sm hover:bg-assay hover:text-shale disabled:opacity-60 whitespace-nowrap">
            {watched ? "\u2713 Watching" : "+ Watchlist"}
          </button>
        </div>
        <div className="flex items-center gap-3 ml-auto">
          <a href="mailto:advertise@getorelens.com?subject=Spotlight%20Inquiry"
             className="text-ash text-[11px] hover:text-assay whitespace-nowrap">
            Your company&apos;s story here &middot; <span className="underline">Advertise</span>
          </a>
          <span className="text-ash/60 text-[10px] whitespace-nowrap">Paid placement</span>
          <button onClick={dismiss} aria-label="Dismiss"
            className="text-ash hover:text-bone text-lg leading-none px-1">&times;</button>
        </div>
      </div>
    </div>
  );
}
