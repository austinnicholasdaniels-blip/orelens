const STYLE: Record<string, string> = {
  A: "border-oxide text-oxide",
  B: "border-oxide/60 text-oxide/80",
  C: "border-assay text-assay",
  D: "border-hazard/70 text-hazard/90",
  F: "border-hazard text-hazard",
};

export default function GradeChip({ grade }: { grade?: string | null }) {
  if (!grade) return <span className="text-ash">—</span>;
  return <span className={`assay-stamp text-base py-0.5 ${STYLE[grade] ?? "border-ash text-ash"}`}>{grade}</span>;
}
