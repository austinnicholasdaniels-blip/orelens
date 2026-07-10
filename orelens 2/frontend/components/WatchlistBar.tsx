"use client";
import { useEffect, useState } from "react";
import { fetchWatchlist, removeFromWatchlist } from "./watchlistClient";

export default function WatchlistBar() {
  const [list, setList] = useState<string[]>([]);
  useEffect(() => { fetchWatchlist().then(setList); }, []);
  if (list.length === 0) return null;

  const remove = async (t: string) => setList(await removeFromWatchlist(t));

  return (
    <div className="flex items-center gap-2 flex-wrap mb-4">
      <span className="text-ash text-xs uppercase tracking-widest">Watchlist</span>
      {list.map((t) => (
        <span key={t} className="flex items-center gap-1.5 bg-tray border border-seam rounded-sm px-2.5 py-1 text-sm">
          <a href={`/ticker/${t}`} className="font-mono text-assay hover:underline">{t}</a>
          <button onClick={() => remove(t)} aria-label={`Remove ${t}`}
            className="text-ash hover:text-hazard text-xs leading-none">&times;</button>
        </span>
      ))}
    </div>
  );
}
