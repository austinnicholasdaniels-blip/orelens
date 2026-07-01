import { fmt } from "@/lib/api";

type Tranche = { strike: number; expiry: string; quantity: number; kind: string; itm: boolean };

export default function WarrantOverhangMap({ warrants }: { warrants: Tranche[] }) {
  if (!warrants?.length) return <p className="text-ash text-sm">No outstanding warrants on file.</p>;
  const max = Math.max(...warrants.map((w) => w.quantity));
  return (
    <div className="bg-tray border border-seam rounded-sm p-4">
      <p className="text-xs uppercase tracking-widest text-ash mb-3">Warrant Overhang Map</p>
      <div className="space-y-2">
        {warrants.map((w, i) => (
          <div key={i} className="flex items-center gap-3 text-sm">
            <span className="font-mono w-16 text-right">${w.strike.toFixed(2)}</span>
            <div className="flex-1 h-5 bg-shale rounded-sm overflow-hidden">
              <div className={`h-full ${w.itm ? "bg-oxide/80" : "bg-seam"}`}
                   style={{ width: `${(w.quantity / max) * 100}%` }} />
            </div>
            <span className="font-mono text-ash w-20">{fmt.shares(w.quantity)}</span>
            <span className="text-xs text-ash w-24">{w.expiry}</span>
            {w.itm && <span className="text-xs text-oxide">ITM</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
