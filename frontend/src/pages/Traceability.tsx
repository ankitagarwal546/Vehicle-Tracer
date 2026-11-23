import { Check, RotateCcw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api, artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Badge, Empty, PlateText, formatInZone, seconds, type Tone } from "../components/ui";
import type { Entity, EntityLink, ReviewStatus } from "../types";

const fmt = (value: number | null) => (value === null ? "n/a" : value.toFixed(2));
const TIERS: Record<string, string> = {
  strong_plate: "Consistent plate characters",
  partial_plate: "Partial plate plus visual similarity",
  legacy_unverified: "Older analysis, re-run required",
};
const STATUS: Record<ReviewStatus, { label: string; tone: Tone }> = {
  proposed: { label: "Possible link", tone: "amber" },
  confirmed: { label: "Confirmed vehicle", tone: "emerald" },
  rejected: { label: "Rejected", tone: "slate" },
};
const TEMPORAL: Record<EntityLink["temporal_status"], { label: string; tone: Tone }> = {
  plausible: { label: "Time plausible", tone: "emerald" },
  weak: { label: "Time weak", tone: "amber" },
  implausible: { label: "Time implausible", tone: "crimson" },
  unavailable: { label: "Time not validated", tone: "amber" },
};

export default function Traceability({ caseId, entities, clipCount, onOpenVehicle, onChanged, onError }: {
  caseId: string | null;
  entities: Entity[];
  clipCount: number;
  onOpenVehicle: (id: string) => void;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [filter, setFilter] = useState<ReviewStatus>("proposed");
  const [busy, setBusy] = useState<string | null>(null);
  const counts = useMemo(() => ({
    proposed: entities.filter((e) => e.review_status === "proposed").length,
    confirmed: entities.filter((e) => e.review_status === "confirmed").length,
    rejected: entities.filter((e) => e.review_status === "rejected").length,
  }), [entities]);
  const visible = entities.filter((entity) => entity.review_status === filter);

  const review = async (entity: Entity, decision: ReviewStatus) => {
    if (!caseId) return;
    setBusy(entity.id);
    try {
      await api.reviewLink(caseId, entity.id, decision);
      await onChanged();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!entities.length) {
    return (
      <div className="panel">
        <Empty title="No possible cross-camera links">
          {clipCount < 2 ? "Add at least two clips to trace a vehicle across cameras."
            : "No pair of tracks had compatible plate characters corroborated by visual or time evidence. Similar colour, body type or model alone never creates a link."}
        </Empty>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="panel flex flex-wrap items-center gap-1 p-1" role="group" aria-label="Filter links by review status">
        {(["proposed", "confirmed", "rejected"] as ReviewStatus[]).map((key) => (
          <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)} className={`px-3 py-1.5 text-xs font-medium ${filter === key ? "bg-navy text-white" : "text-muted hover:bg-canvas"}`}>
            {key === "proposed" ? "To review" : STATUS[key].label} <span className="num">{counts[key]}</span>
          </button>
        ))}
      </div>
      {!visible.length && <div className="panel"><Empty title={`No ${filter === "proposed" ? "links awaiting review" : `${filter} links`}`} /></div>}
      {visible.map((entity) => {
        const status = STATUS[entity.review_status];
        const confirmed = entity.review_status === "confirmed";
        return (
          <section key={entity.id} className="panel">
            <div className="panel-head flex-wrap">
              <span className="flex flex-wrap items-center gap-2"><Badge tone={status.tone}>{status.label}</Badge><span className="font-normal text-muted">{TIERS[entity.evidence_tier] ?? entity.evidence_tier}</span></span>
              <span className="flex flex-wrap items-center gap-2"><span className="label">{confirmed ? "Unified plate" : "Plate if merged"}</span><PlateText text={entity.fused_plate.text} /></span>
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
                      <button className="mb-3 flex min-w-0 gap-3 border border-line p-2 text-left hover:bg-canvas" onClick={() => onOpenVehicle(stop.vehicle_id)}>
                        <span className="h-16 w-24 shrink-0 bg-slate-100 sm:h-20 sm:w-28">{stop.best_crop && <img src={artifactUrl(stop.best_crop)} alt={`Sighting at ${stop.camera_label}`} className="h-full w-full object-cover" />}</span>
                        <span className="min-w-0 space-y-1">
                          <span className="block text-xs font-semibold">{stop.camera_label}{stop.location ? ` · ${stop.location}` : ""}</span>
                          <span className={`num block text-2xs ${stop.absolute_time ? "text-muted" : "text-amber-800"}`}>{stop.absolute_time ? formatInZone(stop.absolute_time, stop.timezone) : "Capture time missing"} · clip {seconds(stop.first_seen_sec)}–{seconds(stop.last_seen_sec)}</span>
                          <span className="flex flex-wrap items-center gap-2"><span className="label">Plate read</span><PlateText text={stop.plate} size="sm" /></span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
                <div className="overflow-x-auto border-t border-line">
                  <table className="w-full min-w-[640px] border-collapse text-xs">
                    <thead><tr><th className="th">Plate overlap</th><th className="th">Contradictions</th><th className="th">Visual</th><th className="th">Attributes</th><th className="th">Temporal check</th></tr></thead>
                    <tbody>{entity.links.map((link) => {
                      const temporal = TEMPORAL[link.temporal_status] ?? TEMPORAL.unavailable;
                      return (
                        <tr key={`${link.a}-${link.b}`}>
                          <td className="td num">{link.plate_compared ? `${link.plate_exact} of ${link.plate_compared} exact` : "No overlap"}</td>
                          <td className="td num">{link.plate_contradictions ?? 0}</td>
                          <td className="td num">{fmt(link.visual)}</td>
                          <td className="td num">{fmt(link.attributes)}</td>
                          <td className="td"><Badge tone={temporal.tone}>{temporal.label}</Badge><div className="mt-0.5 text-2xs text-muted">{link.temporal_note}</div><div className="text-2xs text-muted">{link.location_context}</div></td>
                        </tr>
                      );
                    })}</tbody>
                  </table>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2">
                  <span className="text-2xs text-muted">{entity.reviewed_by ? `Reviewed by ${entity.reviewed_by}${entity.reviewed_at ? `, ${new Date(entity.reviewed_at).toLocaleString()}` : ""}` : "Not reviewed. Compare both sightings before merging."}</span>
                  <span className="flex gap-1">
                    {entity.review_status === "proposed" ? (
                      <>
                        <button className="btn" disabled={busy === entity.id} onClick={() => review(entity, "rejected")}><X size={16} /> Reject</button>
                        <button className="btn btn-primary" disabled={busy === entity.id} onClick={() => review(entity, "confirmed")}><Check size={16} /> Confirm same vehicle</button>
                      </>
                    ) : <button className="btn" disabled={busy === entity.id} onClick={() => review(entity, "proposed")}><RotateCcw size={16} /> Reopen review</button>}
                  </span>
                </div>
              </div>
              <div className="min-w-0">
                {confirmed ? <Shortlist result={entity.match_result} /> : (
                  <details>
                    <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Registry result if this link is correct</summary>
                    <Shortlist result={entity.match_result} />
                  </details>
                )}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
