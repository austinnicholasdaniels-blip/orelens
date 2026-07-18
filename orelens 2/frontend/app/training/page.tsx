"use client";
import { useEffect, useState } from "react";
import ConversionBand from "@/components/ConversionBand";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function toEmbed(url: string): string {
  // accept normal YouTube/Vimeo links and convert to embeddable form
  const yt = url.match(/(?:youtu\.be\/|v=|\/shorts\/)([\w-]{6,})/);
  if (yt) return `https://www.youtube.com/embed/${yt[1]}`;
  const vim = url.match(/vimeo\.com\/(\d+)/);
  if (vim) return `https://player.vimeo.com/video/${vim[1]}`;
  return url;
}

export default function Training() {
  const [video, setVideo] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/site-config`)
      .then((r) => r.json())
      .then((d) => { setVideo(d.training_video_url); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-10">
      <div className="text-center pt-4">
        <p className="text-assay text-xs uppercase tracking-[0.4em] mb-3">Free Training</p>
        <h1 className="font-display text-5xl tracking-wide leading-tight">
          Watch OreLens find a dilution trap.
        </h1>
        <p className="text-bone/90 text-xl max-w-2xl mx-auto mt-4 leading-relaxed">
          A recorded walkthrough of the terminal - real tickers, real filings:
          how the grades work, how the Unlock Calendar flags paper before it
          free-trades, and how The Assayer stress-tests a trade idea.
        </p>
      </div>

      {video ? (
        <div className="relative w-full rounded-sm overflow-hidden border border-seam"
             style={{ paddingTop: "56.25%" }}>
          <iframe src={toEmbed(video)} title="OreLens Training"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="absolute inset-0 w-full h-full" />
        </div>
      ) : (
        <div className="bg-tray border border-seam rounded-sm p-12 text-center">
          <p className="font-display text-2xl tracking-wide">
            {loaded ? "The first training session is being recorded now." : "Loading\u2026"}
          </p>
          <p className="text-ash mt-2">
            Check back shortly - or go straight to the terminal.
          </p>
        </div>
      )}

      <div className="text-center">
        <a href="/training-deck.pdf" target="_blank" rel="noopener"
           className="inline-block border border-assay text-assay font-display tracking-wide text-lg px-7 py-2.5 rounded-sm hover:bg-assay hover:text-shale transition-colors">
          View the training slide deck &rarr;
        </a>
        <p className="text-ash text-xs mt-2">The full deck from the video - grades, the Unlock Calendar, the registry, The Assayer.</p>
      </div>

      <div className="grid sm:grid-cols-3 gap-3">
        {[
          ["What you'll see", "The full dashboard - every scanner, live."],
          ["What you'll learn", "How to read a dilution grade and an unlock date."],
          ["What it costs", "Nothing. The training is free, start to finish."],
        ].map(([t, d]) => (
          <div key={t} className="bg-tray border border-seam rounded-sm p-4">
            <p className="text-assay font-display text-xl tracking-wide">{t}</p>
            <p className="text-bone/85 text-sm mt-1.5">{d}</p>
          </div>
        ))}
      </div>

      <ConversionBand context="Liked what you saw? The terminal is waiting." />
    </div>
  );
}
