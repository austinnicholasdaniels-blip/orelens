const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getScanner(name: string, params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${API}/api/scanners/${name}${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`scanner ${name} failed`);
  return res.json();
}

export async function getTicker(symbol: string) {
  const res = await fetch(`${API}/api/tickers/${symbol}`, { cache: "no-store" });
  if (!res.ok) throw new Error("ticker not found");
  return res.json();
}

export const fmt = {
  money: (n?: number | null) =>
    n == null ? "—" : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${n.toLocaleString()}`,
  shares: (n?: number | null) => (n == null ? "—" : `${(n / 1e6).toFixed(1)}M`),
  pct: (n?: number | null) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`),
};
