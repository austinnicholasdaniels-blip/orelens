"use client";
import { useEffect, useState } from "react";
import { addToWatchlist, fetchWatchlist, removeFromWatchlist } from "./watchlistClient";

export default function WatchButton({ ticker }: { ticker: string }) {
  const [watched, setWatched] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchWatchlist().then((list) => setWatched(list.includes(ticker)));
  }, [ticker]);

  const toggle = async () => {
    setBusy(true);
    const list = watched
      ? await removeFromWatchlist(ticker)
      : await addToWatchlist(ticker);
    setWatched(list.includes(ticker));
    setBusy(false);
  };

  return (
    <button onClick={toggle} disabled={busy}
      aria-label={watched ? "Remove from watchlist" : "Add to watchlist"}
      className={`ml-auto flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-sm border transition-colors disabled:opacity-60 ${
        watched
          ? "border-assay text-assay bg-assay/10"
          : "border-seam text-ash hover:border-assay hover:text-assay"}`}>
      <span className="text-base leading-none">{watched ? "\u2605" : "\u2606"}</span>
      {watched ? "Watching" : "Watch"}
    </button>
  );
}
