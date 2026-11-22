import { artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Empty, PlateText, seconds } from "../components/ui";
import type { Entity } from "../types";

const fmt = (value: number | null) => (value === null ? "n/a" : value.toFixed(3));

export default function Traceability({ entities, clipCount, onOpenVehicle }: {
  entities: Entity[];
  clipCount: number;
  onOpenVehicle: (id: string) => void;
}) {
  if (!entities.length) {
    return (
      <div className="panel">
        <Empty title="No cross-camera links">
          {clipCount < 2 ? "Add at least two clips to trace a vehicle across cameras." : "No pair of tracks cleared the re-identification threshold."}
        </Empty>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {entities.map((entity) => (
        <section key={entity.id} className="panel">
          <div className="panel-head flex-wrap">
            <span className="flex items-center gap-2">Unified vehicle <span className="num font-normal text-muted">{entity.id}</span></span>
            <span className="flex items-center gap-2"><span className="label">Fused plate</span><PlateText text={entity.fused_plate.text} size="lg" /></span>
          </div>
          <div className="grid items-start xl:grid-cols-[minmax(0,8fr)_minmax(0,5fr)]">
            <div className="min-w-0 border-b border-line xl:border-b-0 xl:border-r">
              <ol>
                {entity.timeline.map((stop, index) => (
                  <li key={stop.vehicle_id} className="grid grid-cols-[24px_minmax(0,1fr)] gap-2 px-3 pt-3">
                    <div className="flex flex-col items-center">
                      <span className="num flex h-5 w-5 items-center justify-center border border-navy bg-navy-tint text-2xs text-navy">{index + 1}</span>
                      {index < entity.timeline.length - 1 && <span className="w-px flex-1 bg-slate-300" />}
                    </div>
                    <button className="mb-3 flex gap-3 border border-line p-2 text-left hover:bg-canvas" onClick={() => onOpenVehicle(stop.vehicle_id)}>
                      <span className="h-20 w-28 shrink-0 bg-slate-100">{stop.best_crop && <img src={artifactUrl(stop.best_crop)} alt={`Sighting at ${stop.camera_label}`} className="h-full w-full object-cover" />}</span>
                      <span className="min-w-0 space-y-1">
                        <span className="block text-xs font-semibold">{stop.camera_label}{stop.location ? ` · ${stop.location}` : ""}</span>
                        <span className="num block text-2xs text-muted">{stop.absolute_time ? new Date(stop.absolute_time).toLocaleString() : "Absolute time not supplied"} · clip {seconds(stop.first_seen_sec)}–{seconds(stop.last_seen_sec)}</span>
                        <span className="flex flex-wrap items-center gap-2"><span className="label">Contributed</span><PlateText text={stop.plate} size="sm" /></span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              <div className="overflow-x-auto border-t border-line">
                <table className="w-full min-w-[520px] border-collapse text-xs">
                  <thead><tr><th className="th">Link score</th><th className="th">Visual</th><th className="th">Plate</th><th className="th">Attributes</th><th className="th">Temporal check</th></tr></thead>
                  <tbody>{entity.links.map((link) => (
                    <tr key={`${link.a}-${link.b}`}>
                      <td className="td num font-semibold">{link.score.toFixed(3)}</td><td className="td num">{fmt(link.visual)}</td><td className="td num">{fmt(link.plate)}</td><td className="td num">{fmt(link.attributes)}</td><td className="td text-2xs text-muted">{link.temporal_note}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
            <div className="min-w-0"><Shortlist result={entity.match_result} /></div>
          </div>
        </section>
      ))}
    </div>
  );
}
