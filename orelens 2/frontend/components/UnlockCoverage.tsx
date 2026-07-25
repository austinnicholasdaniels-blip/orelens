"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function UnlockCoverage() {
  const [d, setD] = useState<Record<string, string[] | number | string> | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/unlock-coverage`)
      .then((r) => r.json())
      .then(setD)
      .catch(() => {});
  }, []);

  if (!d) return null;

  return (
    <div className="bg-tray border border-assay rounded-sm p-4 mb-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-assay text-xs uppercase tracking-[0.3em]">
          Coverage
        </span>
        <span className="text-bone/90 text-sm">
          Tracking {String(d.financings_tracked)} financings across{" "}
          {String(d.companies_with_financings)} companies ·{" "}
          {String(d.with_projected_unlock_date)} with projected unlock dates
        </span>
        <button
          onClick={() => setOpen(!open)}
          className="ml-auto text-assay text-xs hover:underline"
        >
          {open ? "Hide limits" : "What this can and can't see →"}
        </button>
      </div>

      {open && (
        <div className="mt-3 grid md:grid-cols-2 gap-4 border-t border-seam pt-3">
          <div>
            <p className="text-oxide text-xs uppercase tracking-[0.2em] mb-1.5">
              What we see
            </p>
            {(d.what_we_see as string[]).map((s) => (
              <p key={s} className="text-bone/85 text-xs mb-1.5">
                <span className="text-oxide mr-1.5">+</span>
                {s}
              </p>
            ))}
          </div>
          <div>
            <p className="text-hazard text-xs uppercase tracking-[0.2em] mb-1.5">
              What we cannot see
            </p>
            {(d.what_we_cannot_see as string[]).map((s) => (
              <p key={s} className="text-bone/85 text-xs mb-1.5">
                <span className="text-hazard mr-1.5">–</span>
                {s}
              </p>
            ))}
          </div>
          <p className="md:col-span-2 text-ash text-xs leading-relaxed border-t border-seam pt-2">
            {String(d.how_to_read_it)}
          </p>
        </div>
      )}
    </div>
  );
}
