// Shared watchlist client: server-side for logged-in members (synced across
// devices), cookie fallback for welcome-flow members who haven't logged in.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WL_COOKIE = "orelens_watchlist";
const SESSION_COOKIE = "orelens_session";

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.split(";").find((c) => c.trim().startsWith(`${name}=`));
  return m ? decodeURIComponent(m.split("=")[1]) : "";
}

export function sessionToken(): string {
  return readCookie(SESSION_COOKIE);
}

export function cookieWatchlist(): string[] {
  return readCookie(WL_COOKIE).split(",").filter(Boolean);
}

export function setCookieWatchlist(list: string[]) {
  document.cookie = `${WL_COOKIE}=${encodeURIComponent(list.join(","))}; max-age=${365 * 24 * 3600}; path=/; SameSite=Lax`;
}

export async function fetchWatchlist(): Promise<string[]> {
  const token = sessionToken();
  if (!token) return cookieWatchlist();
  try {
    const d = await fetch(`${API}/api/watchlist?token=${encodeURIComponent(token)}`).then((r) => r.json());
    if (d?.ok) return d.tickers as string[];
  } catch {}
  return cookieWatchlist();
}

export async function addToWatchlist(ticker: string): Promise<string[]> {
  const token = sessionToken();
  if (token) {
    try {
      const d = await fetch(`${API}/api/watchlist/add`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ticker }),
      }).then((r) => r.json());
      if (d?.ok) return d.tickers as string[];
    } catch {}
  }
  const next = Array.from(new Set([...cookieWatchlist(), ticker]));
  setCookieWatchlist(next);
  return next;
}

export async function removeFromWatchlist(ticker: string): Promise<string[]> {
  const token = sessionToken();
  if (token) {
    try {
      const d = await fetch(`${API}/api/watchlist/remove`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ticker }),
      }).then((r) => r.json());
      if (d?.ok) return d.tickers as string[];
    } catch {}
  }
  const next = cookieWatchlist().filter((t) => t !== ticker);
  setCookieWatchlist(next);
  return next;
}

export async function syncCookieToServer(token: string) {
  const tickers = cookieWatchlist();
  if (tickers.length === 0) return;
  try {
    await fetch(`${API}/api/watchlist/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, tickers }),
    });
  } catch {}
}
