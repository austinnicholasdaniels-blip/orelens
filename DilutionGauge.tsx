import GradeChip from "./GradeChip";

export default function DilutionGauge({ grade }: { grade: any }) {
  if (!grade) return <p className="text-ash text-sm">No grade computed yet.</p>;
  const scale = ["A", "B", "C", "D", "F"];
  return (
    <div className="bg-tray border border-seam rounded-sm p-4">
      <p className="text-xs uppercase tracking-widest text-ash mb-3">Near-Term Dilution Risk</p>
      <div className="flex items-center gap-4">
        <span className={`assay-stamp text-5xl px-4 py-2 ${
          grade.grade <= "B" ? "border-oxide text-oxide" : grade.grade === "C" ? "border-assay text-assay" : "border-hazard text-hazard"}`}>
          {grade.grade}
        </span>
        <div className="flex-1">
          <div className="flex gap-1 mb-2">
            {scale.map((g) => (
              <div key={g} className={`h-2 flex-1 rounded-sm ${
                g === grade.grade ? (g <= "B" ? "bg-oxide" : g === "C" ? "bg-assay" : "bg-hazard") : "bg-seam"}`} />
            ))}
          </div>
          <p className="text-sm text-bone/90">{grade.rationale}</p>
          <p className="text-xs text-ash font-mono mt-1">
            runway {grade.cash_runway_m} mo · adjusted {grade.adjusted_runway_m} mo · overhang {(grade.overhang_ratio * 100).toFixed(1)}%
          </p>
        </div>
      </div>
    </div>
  );
}
