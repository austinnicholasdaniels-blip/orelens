"use client";
import { useState } from "react";
import { syncCookieToServer } from "@/components/watchlistClient";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Login() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    if (!email.includes("@")) { setMsg("Enter the email you subscribed with."); return; }
    setBusy(true); setMsg("");
    try {
      const r = await fetch(`${API}/api/auth/request-code`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const d = await r.json();
      setMsg(d.message ?? "Check your inbox.");
      setStep("code");
    } catch { setMsg("Could not reach the server - try again in a moment."); }
    setBusy(false);
  };

  const verify = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await fetch(`${API}/api/auth/verify-code`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      const d = await r.json();
      if (d.ok && d.token) {
        await syncCookieToServer(d.token);
        const yr = 365 * 24 * 3600;
        document.cookie = `orelens_session=${d.token}; max-age=${yr}; path=/; SameSite=Lax`;
        document.cookie = `orelens_beta=1; max-age=${yr}; path=/; SameSite=Lax`;
        document.cookie = `orelens_member=1; max-age=${yr}; path=/; SameSite=Lax`;
        window.location.href = "/dashboard";
      } else {
        setMsg(d.error ?? "Invalid or expired code.");
      }
    } catch { setMsg("Could not reach the server - try again in a moment."); }
    setBusy(false);
  };

  return (
    <div className="max-w-md mx-auto pt-16 space-y-6">
      <div className="text-center">
        <p className="text-ash text-xs tracking-[0.3em] uppercase mb-2">Members</p>
        <h1 className="font-display text-4xl tracking-wide">Log in to OreLens</h1>
        <p className="text-ash text-sm mt-2">
          No passwords. We email you a 6-digit code.
        </p>
      </div>

      <div className="bg-tray border border-seam rounded-sm p-6 space-y-4">
        {step === "email" ? (
          <>
            <input type="email" value={email} placeholder="Email you subscribed with"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && requestCode()}
              className="w-full bg-shale border border-seam rounded-sm px-4 py-3 text-bone placeholder:text-ash focus:border-assay outline-none" />
            <button onClick={requestCode} disabled={busy}
              className="w-full bg-assay text-shale font-display tracking-wide font-semibold py-3 rounded-sm hover:opacity-90 disabled:opacity-60">
              {busy ? "Sending\u2026" : "Email me a login code"}
            </button>
          </>
        ) : (
          <>
            <p className="text-ash text-sm">Code sent to <span className="text-bone">{email}</span></p>
            <p className="bg-assay/15 border border-assay text-assay text-sm font-semibold rounded-sm px-3 py-2 text-center">
              {"\u26a0"} Don&apos;t see it? Check your SPAM or junk folder - login
              codes sometimes land there.
            </p>
            <input inputMode="numeric" maxLength={6} value={code} placeholder="6-digit code"
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              onKeyDown={(e) => e.key === "Enter" && verify()}
              className="w-full bg-shale border border-seam rounded-sm px-4 py-3 text-bone text-center text-2xl tracking-[0.5em] font-mono placeholder:text-ash placeholder:text-base placeholder:tracking-normal focus:border-assay outline-none" />
            <button onClick={verify} disabled={busy || code.length !== 6}
              className="w-full bg-assay text-shale font-display tracking-wide font-semibold py-3 rounded-sm hover:opacity-90 disabled:opacity-60">
              {busy ? "Checking\u2026" : "Log in"}
            </button>
            <button onClick={() => { setStep("email"); setCode(""); setMsg(""); }}
              className="w-full text-ash text-sm hover:text-assay">
              Use a different email
            </button>
          </>
        )}
        {msg && <p className="text-ash text-sm text-center">{msg}</p>}
      </div>

      <p className="text-ash text-xs text-center">
        Not a member yet? <a href="/pricing" className="text-assay hover:underline">See founding-member pricing</a>
      </p>
    </div>
  );
}
