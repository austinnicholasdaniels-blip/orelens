"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const COOKIE = "orelens_beta";
const MAX_AGE = 45 * 24 * 60 * 60; // 45 days

const COUNTRY_CODES = [
  { code: "+1", label: "+1 (US / Canada)" },
  { code: "+44", label: "+44 (UK)" },
  { code: "+61", label: "+61 (Australia)" },
  { code: "+64", label: "+64 (New Zealand)" },
  { code: "+49", label: "+49 (Germany)" },
  { code: "+33", label: "+33 (France)" },
  { code: "+41", label: "+41 (Switzerland)" },
  { code: "+971", label: "+971 (UAE)" },
  { code: "+65", label: "+65 (Singapore)" },
  { code: "+852", label: "+852 (Hong Kong)" },
  { code: "+other", label: "Other" },
];

const ACCOUNT_SIZES = ["Under $10K", "$10K - $50K", "$50K - $250K", "$250K - $1M", "$1M+"];

function hasCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${COOKIE}=`));
}

export default function BetaGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "gated" | "open">("checking");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [cc, setCc] = useState("+1");
  const [phone, setPhone] = useState("");
  const [size, setSize] = useState(ACCOUNT_SIZES[2]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setState(hasCookie() ? "open" : "gated"); }, []);

  const submit = async () => {
    setErr("");
    if (!name.trim() || !email.trim() || !phone.trim()) {
      setErr("All fields are required for beta access.");
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/beta/signup`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, country_code: cc, phone, account_size: size }),
      });
      const d = await r.json();
      if (d.error) { setErr(d.error); setBusy(false); return; }
      document.cookie = `${COOKIE}=${d.token}; max-age=${MAX_AGE}; path=/; SameSite=Lax`;
      setState("open");
    } catch {
      setErr("Couldn't reach the server - it may be waking up. Try again in ~30s.");
    }
    setBusy(false);
  };

  if (state === "open") return <>{children}</>;
  if (state === "checking") return <p className="text-ash text-center py-20">Loading&hellip;</p>;

  return (
    <div className="max-w-lg mx-auto py-10">
      <div className="bg-tray border border-assay rounded-sm p-8">
        <p className="text-assay text-xs tracking-[0.3em] uppercase mb-2 text-center">Private Beta</p>
        <h2 className="font-display text-3xl tracking-wide text-center mb-2">
          Become a First-Access Member
        </h2>
        <p className="text-ash text-sm text-center mb-6">
          OreLens is in closed beta. Enter your details for full access to every
          screener, the Unlock Calendar, and the promotion registry - free for
          45 days while we build.
        </p>

        <div className="space-y-3">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Full name"
            className="w-full bg-shale border border-seam rounded-sm px-4 py-2.5 text-sm placeholder:text-ash focus:border-assay focus:outline-none" />
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email"
            placeholder="Email address"
            className="w-full bg-shale border border-seam rounded-sm px-4 py-2.5 text-sm placeholder:text-ash focus:border-assay focus:outline-none" />
          <div className="flex gap-2">
            <select value={cc} onChange={(e) => setCc(e.target.value)}
              className="bg-shale border border-seam rounded-sm px-2 py-2.5 text-sm w-44">
              {COUNTRY_CODES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
            </select>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel"
              placeholder="Phone number"
              className="flex-1 bg-shale border border-seam rounded-sm px-4 py-2.5 text-sm placeholder:text-ash focus:border-assay focus:outline-none" />
          </div>
          <div>
            <p className="text-ash text-xs uppercase tracking-widest mb-1.5">Trading account size</p>
            <select value={size} onChange={(e) => setSize(e.target.value)}
              className="w-full bg-shale border border-seam rounded-sm px-2 py-2.5 text-sm">
              {ACCOUNT_SIZES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>

          {err && <p className="text-hazard text-sm">{err}</p>}

          <button onClick={submit} disabled={busy}
            className="w-full bg-assay text-shale font-semibold px-6 py-3 rounded-sm font-display text-lg tracking-wide hover:opacity-90 disabled:opacity-50">
            {busy ? "Unlocking..." : "Unlock Beta Access"}
          </button>
          <p className="text-ash text-xs text-center">
            Your access stays active on this browser for 45 days. We never sell
            your information.
          </p>
        </div>
      </div>
    </div>
  );
}
