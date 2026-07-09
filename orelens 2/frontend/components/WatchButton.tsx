"use client";
import { useEffect, useState } from "react";
import { getWatchlist, setWatchlist } from "./SpotlightFooter";

export default function WatchButton({ ticker }: { ticker: string }) {
  const [watched, setWatched] = useState(false);
  useEffect(() => setWatched(getWatchlist().includes(ticker)), [ticker]);

  const toggle = () => {
    const wl = getWatchlist();
    const next = watched ? wl.filter((t) => t !== ticker) : [...wl, ticker];
    setWatchlist(next);
    setWatched(!watched);
  };

  return (
    <button onClick={toggle} aria-label={watched ? "Remove from watchlist" : "Add to watchlist"}
      className={`ml-auto flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-sm border transition-colors ${
        watched
          ? "border-assay text-assay bg-assay/10"
          : "border-seam text-ash hover:border-assay hover:text-assay"}`}>
      <span className="text-base leading-none">{watched ? "\u2605" : "\u2606"}</span>
      {watched ? "Watching" : "Watch"}
    </button>
  );
}
