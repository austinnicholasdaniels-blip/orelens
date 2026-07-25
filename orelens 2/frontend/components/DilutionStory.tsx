"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Story = { grade: string | null; flags: string[]; story: string; disclaimer: string };

export default function DilutionStory({ ticker }: { ticker: string }) {
  const [s, setS] = useState<Story | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/dilution-story/${ticker}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { setS(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [ticker]);

  if (loading) return null;
  if (!s || !s.story) return null;

  return (
    <div className="bg-tray border border-assay rounded-sm p-5">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-assay text-xs uppercase tracking-[0.3em]">The Dilution Story</span>
        {s.flags.map((f) => (
          <span key={f} className="text-[10px] uppercase tracking-wide border border-hazard/60 text-hazard rounded-sm px-1.5 py-0.5">
            {f}
          </span>
        ))}
      </div>
      <p className="text-bone/95 leading-relaxed">{s.story}</p>
      <p className="text-ash text-[11px] mt-3">{s.disclaimer}</p>
    </div>
  );
}
