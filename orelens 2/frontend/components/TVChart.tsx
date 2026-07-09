"use client";

const TV_PREFIX: Record<string, string> = {
  TSXV: "TSXV", TSX: "TSX", CSE: "CSE", NEO: "NEO",
  NYSE: "NYSE", NASDAQ: "NASDAQ", ASX: "ASX", OTC: "OTC",
};

export default function TVChart({ ticker, exchange }: { ticker: string; exchange: string }) {
  const prefix = TV_PREFIX[exchange?.toUpperCase()] ?? "TSXV";
  const symbol = `${prefix}:${ticker.toUpperCase()}`;
  const src =
    "https://s.tradingview.com/widgetembed/?" +
    new URLSearchParams({
      symbol,
      interval: "D",
      theme: "dark",
      style: "1",            // candles
      locale: "en",
      hide_top_toolbar: "0",
      hide_side_toolbar: "1",
      allow_symbol_change: "0",
      save_image: "0",
      withdateranges: "1",
      backgroundColor: "#1A1E1C",
      gridColor: "#2A302D",
    }).toString();

  return (
    <div className="w-full overflow-hidden rounded-sm border border-seam bg-tray">
      <iframe
        key={symbol}
        src={src}
        style={{ width: "100%", height: 420, border: 0, display: "block" }}
        allowFullScreen
        title={`${symbol} chart`}
      />
    </div>
  );
}
