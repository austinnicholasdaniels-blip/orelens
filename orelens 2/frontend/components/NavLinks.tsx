"use client";
import { useEffect, useState } from "react";

export default function NavLinks() {
  const [member, setMember] = useState(false);
  useEffect(() => {
    setMember(document.cookie.split(";").some((c) =>
      c.trim().startsWith("orelens_member=")));
  }, []);

  return (
    <>
      <a href="/dashboard" className="text-bone hover:text-assay">Scanners</a>
      <a href="/news" className="text-bone hover:text-assay">News</a>
      <a href="/research/promotions" className="text-bone hover:text-assay">Research</a>
      <a href="/digest" className="text-bone hover:text-assay">Digest</a>
      <a href="/assayer" className={member ? "text-assay hover:opacity-80" : "text-bone hover:text-assay"}>Assayer</a>
      {!member && (
        <a href="/pricing" className="text-assay hover:opacity-80">Pricing</a>
      )}
      {!member && (
        <a href="/login" className="text-bone hover:text-assay">Log in</a>
      )}
    </>
  );
}
