import { AlertTriangle, Check, Clock3, RotateCcw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api, artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Badge, Empty, Notice, PageHeader, PlateText, formatInZone, seconds, type Tone } from "../components/ui";
import type { Clip, Entity, EntityLink, ReviewStatus, TimelineEntry } from "../types";

const fmt = (value: number | null) => (value === null ? "n/a" : value.toFixed(2));
const TIERS: Record<string, string> = {
  strong_plate: "Consistent plate characters",
  partial_plate: "Partial plate plus visual similarity",
  legacy_unverified: "Older analysis, re-run required",
};
const STATUS: Record<ReviewStatus, { label: string; tone: Tone }> = {
  proposed: { label: "Proposed link", tone: "amber" },
  confirmed: { label: "Investigator confirmed", tone: "emerald" },
  rejected: { label: "Rejected", tone: "slate" },
};
const TABS: { key: ReviewStatus; label: string }[] = [
  { key: "proposed", label: "Proposed, awaiting review" },
  { key: "confirmed", label: "Investigator confirmed" },
  { key: "rejected", label: "Rejected" },
];
const TEMPORAL: Record<EntityLink["temporal_status"], { label: string; tone: Tone }> = {
  plausible: { label: "Time plausible", tone: "emerald" },
  weak: { label: "Time weak", tone: "amber" },
  implausible: { label: "Time implausible", tone: "crimson" },
  unavailable: { label: "Time not validated", tone: "amber" },
};

const WIDTH = 960;
const LABEL_WIDTH = 150;
const NO_TIME_WIDTH = 130;
const LANE_HEIGHT = 44;
const TOP = 12;
const AXIS_HEIGHT = 28;

function CameraTimeline({ entities, clips, onSelect }: { entities: Entity[]; clips: Clip[]; onSelect: (entity: Entity) => void }) {
  const drawn = entities.filter((entity) => entity.review_status !== "rejected");
  const lanes = new Map(clips.map((clip, index) => [clip.id, index]));
  const stops = drawn.flatMap((entity) => entity.timeline);
  const times = stops.filter((stop) => stop.absolute_time).map((stop) => Date.parse(stop.absolute_time!));
  const undated = stops.some((stop) => !stop.absolute_time);
  const start = times.length ? Math.min(...times) : 0;
  const end = times.length ? Math.max(...times) : 0;
  const plotEnd = WIDTH - (undated ? NO_TIME_WIDTH + 18 : 18);
  const height = TOP + clips.length * LANE_HEIGHT + AXIS_HEIGHT;
  const laneY = (clipId: string) => TOP + (lanes.get(clipId) ?? 0) * LANE_HEIGHT + LANE_HEIGHT / 2;
  const undatedCount = new Map<string, number>();
  const place = new Map<string, number>();
  drawn.forEach((entity) => entity.timeline.forEach((stop) => {
    if (stop.absolute_time) {
      const span = end - start;
      place.set(`${entity.id}:${stop.vehicle_id}`, span ? LABEL_WIDTH + 12 + ((Date.parse(stop.absolute_time) - start) / span) * (plotEnd - LABEL_WIDTH - 24) : (LABEL_WIDTH + plotEnd) / 2);
    } else {
      const used = undatedCount.get(stop.clip_id) ?? 0;
      undatedCount.set(stop.clip_id, used + 1);
      place.set(`${entity.id}:${stop.vehicle_id}`, WIDTH - NO_TIME_WIDTH + 14 + (used % 5) * 22);
    }
  }));
  const label = (value: number) => new Date(value).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
  const describe = (entity: Entity, stop: TimelineEntry) => `${STATUS[entity.review_status].label}. ${stop.camera_label}, plate read ${stop.plate || "none"}, ${stop.absolute_time ? label(Date.parse(stop.absolute_time)) : "capture time missing"}`;

  return (
    <section className="panel" aria-labelledby="camera-timeline">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div>
          <h2 id="camera-timeline" className="text-xs font-semibold">Camera timeline</h2>
          <p className="text-2xs text-muted">Each row is a camera. Each dot is a sighting in a link. Times are shown in your local timezone.</p>
        </div>
        <ul className="flex flex-wrap items-center gap-3 text-2xs text-muted" aria-label="Legend">
          <li className="flex items-center gap-1"><svg width="26" height="6" aria-hidden="true"><line x1="0" y1="3" x2="26" y2="3" stroke="#FBBF24" strokeWidth="2" strokeDasharray="5 3" /></svg>Proposed</li>
          <li className="flex items-center gap-1"><svg width="26" height="6" aria-hidden="true"><line x1="0" y1="3" x2="26" y2="3" stroke="#C4BAFF" strokeWidth="2" /></svg>Confirmed</li>
        </ul>
      </div>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable camera timeline">
        <svg viewBox={`0 0 ${WIDTH} ${height}`} className="block w-full min-w-[680px]" role="group" aria-label={`${drawn.length} links across ${clips.length} cameras`}>
          {undated && (
            <g>
              <rect x={WIDTH - NO_TIME_WIDTH} y={TOP} width={NO_TIME_WIDTH - 2} height={clips.length * LANE_HEIGHT} fill="#2A2113" stroke="#7A5D19" />
              <text x={WIDTH - NO_TIME_WIDTH / 2} y={height - 10} textAnchor="middle" fontSize="11" fill="#FDE68A">No capture time</text>
            </g>
          )}
          {clips.map((clip) => (
            <g key={clip.id}>
              <line x1={LABEL_WIDTH} x2={WIDTH - 2} y1={laneY(clip.id)} y2={laneY(clip.id)} stroke="#2F2850" />
              <text x={0} y={laneY(clip.id) + 4} fontSize="12" fontWeight="600" fill="#F3F1FB">{clip.camera_label.length > 22 ? `${clip.camera_label.slice(0, 21)}…` : clip.camera_label}</text>
            </g>
          ))}
          {drawn.map((entity) => {
            const confirmed = entity.review_status === "confirmed";
            return (
              <g key={entity.id}>
                {entity.timeline.slice(1).map((stop, index) => {
                  const previous = entity.timeline[index];
                  return <line key={stop.vehicle_id} x1={place.get(`${entity.id}:${previous.vehicle_id}`)} y1={laneY(previous.clip_id)} x2={place.get(`${entity.id}:${stop.vehicle_id}`)} y2={laneY(stop.clip_id)} stroke={confirmed ? "#C4BAFF" : "#FBBF24"} strokeWidth="2" strokeDasharray={confirmed ? undefined : "5 3"} />;
                })}
                {entity.timeline.map((stop) => (
                  <g key={stop.vehicle_id} role="button" tabIndex={0} aria-label={describe(entity, stop)} className="cursor-pointer" onClick={() => onSelect(entity)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(entity); } }}>
                    <title>{describe(entity, stop)}</title>
                    <circle cx={place.get(`${entity.id}:${stop.vehicle_id}`)} cy={laneY(stop.clip_id)} r="12" fill="transparent" />
                    <circle cx={place.get(`${entity.id}:${stop.vehicle_id}`)} cy={laneY(stop.clip_id)} r="6" fill={confirmed ? "#C4BAFF" : "#18132C"} stroke={confirmed ? "#18132C" : "#FBBF24"} strokeWidth="2" />
                  </g>
                ))}
              </g>
            );
          })}
          {times.length > 0 && (
            <g fontSize="11" fill="#ABA6C4">
              <text x={LABEL_WIDTH + 2} y={height - 10}>{label(start)}</text>
              {end !== start && <text x={plotEnd} y={height - 10} textAnchor="end">{label(end)}</text>}
            </g>
          )}
        </svg>
      </div>
    </section>
  );
}

export default function Traceability({ caseId, caseTitle, entities, clips, onOpenVehicle, onChanged, onError }: {
  caseId: string | null;
  caseTitle?: string;
  entities: Entity[];
  clips: Clip[];
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
  const clipCount = clips.length;
  const missing = clips.filter((clip) => !clip.recorded_at);

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

  const select = (entity: Entity) => {
    setFilter(entity.review_status);
    window.requestAnimationFrame(() => document.getElementById(`link-${entity.id}`)?.scrollIntoView({ block: "start" }));
  };

  const header = <PageHeader eyebrow="Cross-camera trace" title={caseTitle ?? "Cross-camera trace"} description="Possible sightings of one vehicle across cameras. A link counts only after an investigator confirms it."
    actions={clips.some((clip) => clip.synthetic) ? <Badge tone="amber" title="Clips in this case are synthetic test fixtures">Demo evidence</Badge> : undefined} />;

  if (clipCount < 2) {
    return (
      <>
        {header}
        <div className="panel">
          <Empty title="Cross-camera linking cannot be evaluated">
            {clipCount === 1 ? "This case has one clip, so no comparison between cameras was run. Add a clip from another camera to test re-identification." : "Add at least two clips from different cameras to trace a vehicle."}
          </Empty>
        </div>
      </>
    );
  }

  return (
    <div className="space-y-3">
      {header}
      {missing.length > 0 && (
        <Notice icon={<Clock3 size={15} />} title="Capture time missing">
          {missing.map((clip) => clip.camera_label).join(", ")} {missing.length === 1 ? "has" : "have"} no capture time, so temporal checks cannot be validated for links involving {missing.length === 1 ? "it" : "them"}.
        </Notice>
      )}
      <CameraTimeline entities={entities} clips={clips} onSelect={select} />
      {!entities.length ? (
        <div className="panel">
          <Empty title="No possible cross-camera links">No pair of tracks had compatible plate characters corroborated by visual or time evidence. Similar colour, body type or model alone never creates a link.</Empty>
        </div>
      ) : (
        <>
          <div className="panel flex flex-wrap items-center gap-1 p-1" role="group" aria-label="Filter links by review status">
            {TABS.map(({ key, label }) => (
              <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)} className={`min-h-8 rounded-evidence px-3 py-1.5 text-xs font-medium ${filter === key ? "bg-accent text-white" : "text-muted hover:bg-canvas"}`}>
                {label} <span className="num">{counts[key]}</span>
              </button>
            ))}
          </div>
          {!visible.length && <div className="panel"><Empty title={`No ${filter === "proposed" ? "links awaiting review" : `${filter} links`}`} /></div>}
          {visible.map((entity) => {
            const status = STATUS[entity.review_status];
            const confirmed = entity.review_status === "confirmed";
            const untimed = entity.links.some((link) => link.temporal_status === "unavailable");
            return (
              <section key={entity.id} id={`link-${entity.id}`} className="panel scroll-mt-3" aria-label={`${status.label}: ${entity.timeline.map((stop) => stop.camera_label).join(" to ")}`}>
                <div className="panel-head flex-wrap">
                  <span className="flex flex-wrap items-center gap-2"><Badge tone={status.tone}>{status.label}</Badge><span className="font-normal text-muted">{TIERS[entity.evidence_tier] ?? entity.evidence_tier}</span></span>
                  <span className="flex flex-wrap items-center gap-2"><span className="label">{confirmed ? "Unified plate" : "Plate if merged"}</span><PlateText text={entity.fused_plate.text} /></span>
                </div>
                {untimed && <div className="flex items-center gap-1.5 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-2xs text-amber-950"><AlertTriangle size={13} aria-hidden="true" /> Temporal validation is unavailable for at least one step of this link.</div>}
                <div className="grid items-start xl:grid-cols-[minmax(0,8fr)_minmax(0,5fr)]">
                  <div className="min-w-0 border-b border-line xl:border-b-0 xl:border-r">
                    <ol className="grid gap-2 p-2 md:grid-cols-2">
                      {entity.timeline.map((stop, index) => (
                        <li key={stop.vehicle_id} className="min-w-0">
                          <button className="flex w-full min-w-0 gap-2.5 rounded-evidence border border-line p-2 text-left hover:border-accent hover:bg-canvas" onClick={() => onOpenVehicle(stop.vehicle_id)} aria-label={`Inspect sighting ${index + 1} at ${stop.camera_label}`}>
                            <span className="relative h-16 w-24 shrink-0 overflow-hidden rounded-evidence bg-slate-100 sm:h-20 sm:w-28">
                              {stop.best_crop && <img src={artifactUrl(stop.best_crop)} alt="" className="h-full w-full object-cover" />}
                              <span className="num absolute left-0 top-0 bg-shell px-1 text-2xs text-shell-text">{index + 1}{clips.find((clip) => clip.id === stop.clip_id)?.synthetic ? " · demo" : ""}</span>
                            </span>
                            <span className="min-w-0 space-y-1">
                              <span className="block truncate text-xs font-semibold">{stop.camera_label}{stop.location ? ` · ${stop.location}` : ""}</span>
                              <span className={`num block text-2xs ${stop.absolute_time ? "text-muted" : "font-medium text-amber-900"}`}>{stop.absolute_time ? formatInZone(stop.absolute_time, stop.timezone) : "Capture time missing"}</span>
                              <span className="num block text-2xs text-muted">clip {seconds(stop.first_seen_sec)}–{seconds(stop.last_seen_sec)}</span>
                              <span className="flex flex-wrap items-center gap-1.5"><span className="label">Plate read</span><PlateText text={stop.plate} size="sm" /></span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ol>
                    <div className="overflow-x-auto border-t border-line">
                      <table className="w-full min-w-[640px] border-collapse text-xs">
                        <caption className="sr-only">Evidence for each step of this link</caption>
                        <thead><tr><th scope="col" className="th">Plate contribution</th><th scope="col" className="th">Contradictions</th><th scope="col" className="th">Visual similarity</th><th scope="col" className="th">Attributes</th><th scope="col" className="th">Temporal validation</th></tr></thead>
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
                    <p className="border-t border-line px-3 py-1 text-2xs text-muted">Similarity values are ranking evidence, not probabilities.</p>
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2">
                      <span className="text-2xs text-muted">{entity.reviewed_by ? `Reviewed by ${entity.reviewed_by}${entity.reviewed_at ? `, ${new Date(entity.reviewed_at).toLocaleString()}` : ""}` : "Not reviewed. Compare both sightings before merging."}</span>
                      <span className="flex flex-wrap gap-1">
                        {entity.review_status === "proposed" ? (
                          <>
                            <button className="btn" disabled={busy === entity.id} onClick={() => review(entity, "rejected")}><X size={15} /> Reject</button>
                            <button className="btn btn-primary" disabled={busy === entity.id} onClick={() => review(entity, "confirmed")}><Check size={15} /> Confirm same vehicle</button>
                          </>
                        ) : <button className="btn" disabled={busy === entity.id} onClick={() => review(entity, "proposed")}><RotateCcw size={15} /> Reopen review</button>}
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
        </>
      )}
    </div>
  );
}
