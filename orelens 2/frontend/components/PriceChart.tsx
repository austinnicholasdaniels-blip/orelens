"use client";
import { useEffect, useRef } from "react";
import { createChart, ColorType, LineStyle } from "lightweight-charts";

function sma(data: { time: string; value: number }[], n: number) {
  const out: { time: string; value: number }[] = [];
  for (let i = n - 1; i < data.length; i++) {
    const avg = data.slice(i - n + 1, i + 1).reduce((s, d) => s + d.value, 0) / n;
    out.push({ time: data[i].time, value: avg });
  }
  return out;
}

export default function PriceChart({ prices }: { prices: { time: string; value: number; volume: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !prices?.length) return;
    const chart = createChart(ref.current, {
      height: 320,
      layout: { background: { type: ColorType.Solid, color: "#FFFFFF" }, textColor: "#8A94A4" },
      grid: { vertLines: { color: "#EDF1F5" }, horzLines: { color: "#EDF1F5" } },
      rightPriceScale: { borderColor: "#DDE3EA" },
      timeScale: { borderColor: "#DDE3EA" },
    });
    const line = chart.addAreaSeries({
      lineColor: "#2563EB", topColor: "rgba(37,99,235,0.16)", bottomColor: "rgba(37,99,235,0.0)",
    });
    line.setData(prices.map((p) => ({ time: p.time, value: p.value })));

    const vol = chart.addHistogramSeries({
      priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#DDE3EA",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(prices.map((p) => ({ time: p.time, value: p.volume })));

    const closes = prices.map((p) => ({ time: p.time, value: p.value }));
    if (closes.length >= 50)
      chart.addLineSeries({ color: "#0E9F6E", lineWidth: 1, lineStyle: LineStyle.Solid }).setData(sma(closes, 50));
    if (closes.length >= 200)
      chart.addLineSeries({ color: "#DC2626", lineWidth: 1 }).setData(sma(closes, 200));

    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 });
    onResize();
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [prices]);

  return <div ref={ref} className="w-full border border-seam rounded-sm overflow-hidden" />;
}
