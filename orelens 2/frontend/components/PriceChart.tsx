"use client";
import { useEffect, useRef } from "react";
import { createChart, ColorType, LineStyle } from "lightweight-charts";

type Px = { time: string; value: number; volume: number;
            open?: number; high?: number; low?: number };

function sma(data: { time: string; value: number }[], n: number) {
  const out: { time: string; value: number }[] = [];
  for (let i = n - 1; i < data.length; i++) {
    const avg = data.slice(i - n + 1, i + 1).reduce((s, d) => s + d.value, 0) / n;
    out.push({ time: data[i].time, value: avg });
  }
  return out;
}

const UP = "#0B8F63";
const DOWN = "#C42B2B";

export default function PriceChart({ prices }: { prices: Px[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !prices?.length) return;
    const chart = createChart(ref.current, {
      height: 320,
      layout: { background: { type: ColorType.Solid, color: "#FFFFFF" }, textColor: "#5C6B85" },
      grid: { vertLines: { color: "#EDF1F8" }, horzLines: { color: "#EDF1F8" } },
      rightPriceScale: { borderColor: "#CFD9E8" },
      timeScale: { borderColor: "#CFD9E8" },
    });

    // candles: legacy rows without OHLC render as flat candles at the close
    const candles = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN,
      borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN,
    });
    candles.setData(prices.map((p) => ({
      time: p.time,
      open: p.open ?? p.value,
      high: p.high ?? Math.max(p.open ?? p.value, p.value),
      low: p.low ?? Math.min(p.open ?? p.value, p.value),
      close: p.value,
    })));

    // volume, tinted by candle direction
    const vol = chart.addHistogramSeries({
      priceFormat: { type: "volume" }, priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(prices.map((p) => ({
      time: p.time, value: p.volume,
      color: p.value >= (p.open ?? p.value) ? "rgba(88,176,156,0.35)" : "rgba(212,87,78,0.35)",
    })));

    // moving averages over closes
    const closes = prices.map((p) => ({ time: p.time, value: p.value }));
    if (closes.length >= 50)
      chart.addLineSeries({ color: "#1E4FD8", lineWidth: 1, lineStyle: LineStyle.Solid,
        priceLineVisible: false, lastValueVisible: false }).setData(sma(closes, 50));
    if (closes.length >= 200)
      chart.addLineSeries({ color: "#8FA0BC", lineWidth: 1, lineStyle: LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false }).setData(sma(closes, 200));

    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    window.addEventListener("resize", onResize);
    onResize();
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [prices]);

  return <div ref={ref} className="w-full" />;
}
