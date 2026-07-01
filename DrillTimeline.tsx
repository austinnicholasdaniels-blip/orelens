export default function DrillTimeline({ program, results, comparison }:
  { program: any; results: any[]; comparison?: string | null }) {
  return (
    <div className="bg-tray border border-seam rounded-sm p-4">
      <p className="text-xs uppercase tracking-widest text-ash mb-3">
        Drill Program {program ? `— ${program.name}` : ""}
      </p>
      {program && (
        <p className="text-sm mb-3 font-mono">
          {program.holes_drilled} holes reported · {program.holes_hit} hit ·{" "}
          {program.rigs} rig{program.rigs === 1 ? "" : "s"} · {program.planned_meters?.toLocaleString()} m planned
        </p>
      )}
      <ol className="border-l border-seam pl-4 space-y-3">
        {results.map((r, i) => (
          <li key={i} className="text-sm">
            <span className="text-ash font-mono text-xs mr-2">{r.published.slice(0, 10)}</span>
            <span className="font-mono mr-2">{r.hole || "—"}</span>
            <span className={r.above_benchmark ? "text-assay" : ""}>{r.intercept}</span>
            <span className="text-ash text-xs ml-2">({r.grade_meters} g·m)</span>
          </li>
        ))}
        {results.length === 0 && <li className="text-ash text-sm">Assays pending — no intercepts parsed yet.</li>}
      </ol>
      {comparison && (
        <p className="mt-4 text-sm border border-assay/40 bg-shale rounded-sm p-3 text-bone/90">{comparison}</p>
      )}
    </div>
  );
}
