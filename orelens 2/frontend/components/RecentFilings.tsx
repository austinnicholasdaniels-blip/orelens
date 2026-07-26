"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Doc = {
  published: string | null; headline: string; url: string;
  wire: string; type: string;
};

const TYPE_COLOR: Record<string, string> = {
  "Financing": "border-hazard text-hazard",
  "Promotion / IR": "border-hazard text-hazard",
  "Drill Results": "border-oxide text-oxide",
  "Resource / Study": "border-oxide text-oxide",
  "Production": "border-oxide text-oxide",
  "Corporate": "border-seam text-ash",
  "Release": "border-seam text-ash",
};

export default function RecentFilings({ ticker }: { ticker: string }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [note, setNote] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    fetch(`${API}/api/company-documents/${ticker}?limit=40`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) { setDocs(d.documents); setNote(d.source_note); } })
      .catch(() => setDocs([]));
  }, [ticker]);

  if (docs === null) {
    return (
      <div className="bg-tray border border-seam rounded-sm p-5">
        <p className="text-ash text-xs uppercase tracking-[0.25em] mb-2">Recent Filings & Releases</p>
        <p className="text-ash text-sm">Loading…</p>
      </div>
    );
  }

  const types = Array.from(new Set(docs.map((d) => d.type)));
  const filtered = filter ? docs.filter((d) => d.type === filter) : docs;
  const shown = showAll ? filtered : filtered.slice(0, 8);

  return (
    <div className="bg-tray border border-seam rounded-sm p-5">
      <div className="flex items-baseline gap-2 flex-wrap mb-3">
        <p className="text-ash text-xs uppercase tracking-[0.25em]">
          Recent Filings &amp; Releases
        </p>
        <span className="text-ash text-xs">({docs.length})</span>
        {types.length > 1 && (
          <div className="ml-auto flex gap-1.5 flex-wrap">
            <button onClick={() => setFilter("")}
              className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${
                filter === "" ? "border-assay text-assay" : "border-seam text-ash hover:text-bone"}`}>
              All
            </button>
            {types.map((t) => (
              <button key={t} onClick={() => setFilter(t)}
                className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${
                  filter === t ? "border-assay text-assay" : "border-seam text-ash hover:text-bone"}`}>
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {shown.length === 0 && (
        <p className="text-ash text-sm">
          No releases on file yet for this company. New ones appear here
          automatically as they hit the wire.
        </p>
      )}

      <div className="space-y-2.5">
        {shown.map((d, i) => (
          <a key={i} href={d.url} target="_blank" rel="noopener noreferrer"
             className="block group border-b border-seam/50 last:border-0 pb-2.5 last:pb-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className={`text-[10px] uppercase tracking-wide border rounded-sm px-1.5 ${TYPE_COLOR[d.type] ?? "border-seam text-ash"}`}>
                {d.type}
              </span>
              <span className="text-ash font-mono text-xs">{d.published}</span>
              <span className="text-ash text-[10px] ml-auto">{d.wire}</span>
            </div>
            <p className="text-bone/90 text-sm mt-1 group-hover:text-assay leading-snug">
              {d.headline} <span className="text-assay">↗</span>
            </p>
          </a>
        ))}
      </div>

      {filtered.length > 8 && (
        <button onClick={() => setShowAll(!showAll)}
          className="text-assay text-xs mt-3 hover:underline">
          {showAll ? "Show less" : `Show all ${filtered.length} →`}
        </button>
      )}

      {note && <p className="text-ash text-[11px] mt-3 leading-relaxed">{note}</p>}
    </div>
  );
}
