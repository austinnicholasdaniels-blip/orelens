"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Series = {
  name: string; exchange: string; commodity: string;
  grade: string | null; closes: (number | null)[];
  ohlc: ([number, number, number, number, number] | null)[]; vols: number[];
  last: number | null; period_pct: number | null; day_pct: number | null;
  last_day: string;
};

const GRADE_COLOR: Record<string, string> = {
  A: "text-oxide border-oxide", B: "text-oxide border-oxide",
  C: "text-assay border-assay", D: "text-hazard border-hazard",
  F: "text-hazard border-hazard",
};

const RANGES = [
  { key: 90, label: "3M" },
  { key: 180, label: "6M" },
  { key: 365, label: "1Y" },
];

/** Price line + 50-period moving average + volume bars, drawn as inline SVG. */
function Sparkline({ closes, vols, up }: { closes: (number | null)[]; vols: number[]; up: boolean }) {
  const pts = closes.map((c, i) => [i, c] as [number, number | null]).filter((p) => p[1] != null) as [number, number][];
  if (pts.length < 2) {
    return <div className="h-[86px] flex items-center justify-center text-ash text-xs">no price history</div>;
  }
  const W = 260, H = 86, PAD = 3, VOL_H = 18;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanY = maxY - minY || 1;
  const plotH = H - VOL_H - PAD * 2;
  const sx = (x: number) => PAD + ((x - minX) / (maxX - minX || 1)) * (W - PAD * 2);
  const sy = (y: number) => PAD + (1 - (y - minY) / spanY) * plotH;

  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
  const area = `${line} L${sx(pts[pts.length - 1][0]).toFixed(1)},${(PAD + plotH).toFixed(1)} L${sx(pts[0][0]).toFixed(1)},${(PAD + plotH).toFixed(1)} Z`;

  // 50-period moving average
  const win = Math.min(50, Math.max(5, Math.floor(pts.length / 4)));
  const ma: string[] = [];
  for (let i = win - 1; i < pts.length; i++) {
    const avg = pts.slice(i - win + 1, i + 1).reduce((a, b) => a + b[1], 0) / win;
    ma.push(`${ma.length === 0 ? "M" : "L"}${sx(pts[i][0]).toFixed(1)},${sy(avg).toFixed(1)}`);
  }

  const maxVol = Math.max(...vols, 1);
  const stroke = up ? "#5FBCA4" : "#DD5F55";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[86px]" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`g-${up ? "u" : "d"}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      {vols.map((v, i) => {
        const h = (v / maxVol) * VOL_H;
        return <rect key={i} x={sx(i) - 0.6} y={H - h} width="1.2" height={h} fill="#332D25" />;
      })}
      <path d={area} fill={`url(#g-${up ? "u" : "d"})`} />
      <path d={line} fill="none" stroke={stroke} strokeWidth="1.5" />
      {ma.length > 1 && <path d={ma.join(" ")} fill="none" stroke="#E3B356" strokeWidth="1" strokeDasharray="3 2" opacity="0.75" />}
    </svg>
  );
}

/** Candlestick renderer: green up-candles, red down-candles, wicks, volume. */
function Candles({ ohlc, vols }: { ohlc: (number[] | null)[]; vols: number[] }) {
  const bars = ohlc.map((o, i) => ({ o, i })).filter((b) => b.o) as { o: number[]; i: number }[];
  if (bars.length < 2) {
    return <div className="h-[86px] flex items-center justify-center text-ash text-xs">no price history</div>;
  }
  const W = 260, H = 86, PAD = 3, VOL_H = 16;
  const highs = bars.map((b) => b.o[1]), lows = bars.map((b) => b.o[2]);
  const maxY = Math.max(...highs), minY = Math.min(...lows);
  const spanY = maxY - minY || 1;
  const plotH = H - VOL_H - PAD * 2;
  const n = bars.length;
  const cw = Math.max(1.2, (W - PAD * 2) / n * 0.7);
  const cx = (i: number) => PAD + ((i + 0.5) / n) * (W - PAD * 2);
  const sy = (y: number) => PAD + (1 - (y - minY) / spanY) * plotH;
  const maxVol = Math.max(...vols, 1);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[86px]" preserveAspectRatio="none">
      {vols.map((v, i) => {
        const h = (v / maxVol) * VOL_H;
        return <rect key={`v${i}`} x={cx(i) - cw / 2} y={H - h} width={cw} height={h} fill="#332D25" />;
      })}
      {bars.map(({ o, i }, k) => {
        const [op, hi, lo, cl] = o;
        const up = cl >= op;
        const color = up ? "#5FBCA4" : "#DD5F55";
        const yO = sy(op), yC = sy(cl);
        const top = Math.min(yO, yC);
        const bodyH = Math.max(0.8, Math.abs(yC - yO));
        return (
          <g key={k}>
            <line x1={cx(i)} y1={sy(hi)} x2={cx(i)} y2={sy(lo)} stroke={color} strokeWidth="0.6" />
            <rect x={cx(i) - cw / 2} y={top} width={cw} height={bodyH} fill={color} />
          </g>
        );
      })}
    </svg>
  );
}

export default function ChartGrid({ tickers }: { tickers: string[] }) {
  const [data, setData] = useState<Record<string, Series>>({});
  const [days, setDays] = useState(180);
  const [style, setStyle] = useState<"candles" | "line">("candles");
  const [loading, setLoading] = useState(true);
  const shown = tickers.slice(0, 48);

  useEffect(() => {
    if (shown.length === 0) { setLoading(false); return; }
    setLoading(true);
    fetch(`${API}/api/scanners/chart-data?tickers=${shown.join(",")}&days=${days}`)
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown.join(","), days]);

  if (loading) return <p className="text-ash text-sm py-8 text-center">Drawing charts…</p>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-ash text-xs uppercase tracking-[0.2em]">Range</span>
        {RANGES.map((r) => (
          <button key={r.key} onClick={() => setDays(r.key)}
            className={`text-xs font-mono px-2 py-0.5 rounded-sm border ${
              days === r.key ? "border-assay text-assay" : "border-seam text-ash hover:text-bone"}`}>
            {r.label}
          </button>
        ))}
        <span className="mx-3 text-seam">|</span>
        {(["candles", "line"] as const).map((sv) => (
          <button key={sv} onClick={() => setStyle(sv)}
            className={`text-xs font-mono px-2 py-0.5 rounded-sm border ${
              style === sv ? "border-assay text-assay" : "border-seam text-ash hover:text-bone"}`}>
            {sv === "candles" ? "Candles" : "Line"}
          </button>
        ))}
        <span className="text-ash text-xs ml-auto">
          {shown.length} of {tickers.length} shown
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {shown.map((t) => {
          const s = data[t];
          if (!s) return null;
          const up = (s.period_pct ?? 0) >= 0;
          return (
            <a key={t} href={`/ticker/${t}`}
               className="bg-tray border border-seam rounded-sm p-3 hover:border-assay transition-colors block">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-assay font-semibold">{t}</span>
                <span className="text-ash text-[10px]">{s.exchange}</span>
                {s.grade && (
                  <span className={`ml-auto border rounded-sm px-1.5 text-xs font-display ${GRADE_COLOR[s.grade] ?? "text-ash border-seam"}`}>
                    {s.grade}
                  </span>
                )}
              </div>
              <p className="text-bone/85 text-xs truncate mt-0.5">{s.name}</p>
              {style === "candles"
                ? <Candles ohlc={s.ohlc} vols={s.vols} />
                : <Sparkline closes={s.closes} vols={s.vols} up={up} />}
              <div className="flex items-baseline gap-2 mt-1">
                <span className="font-mono text-bone">{s.last != null ? `$${s.last}` : "—"}</span>
                {s.day_pct != null && (
                  <span className={`font-mono text-xs ${s.day_pct >= 0 ? "text-oxide" : "text-hazard"}`}>
                    {s.day_pct >= 0 ? "+" : ""}{s.day_pct}%
                  </span>
                )}
                <span className={`font-mono text-xs ml-auto ${up ? "text-oxide" : "text-hazard"}`}>
                  {up ? "+" : ""}{s.period_pct ?? 0}% <span className="text-ash">period</span>
                </span>
              </div>
            </a>
          );
        })}
      </div>
      {shown.length === 0 && (
        <p className="text-ash text-center py-8">No companies match these filters.</p>
      )}
    </div>
  );
}
