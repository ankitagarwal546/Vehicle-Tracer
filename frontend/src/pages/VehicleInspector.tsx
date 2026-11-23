import { ArrowLeft, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Badge, Empty, LinkBadge, OutcomeBadge, PlateText, pretty, seconds } from "../components/ui";
import { BODY_TYPES, COLOURS, type VehicleDetail, type VehicleSummary } from "../types";

interface Props {
  caseId: string;
  vehicleId: string | null;
  vehicles: VehicleSummary[];
  onOpenVehicle: (id: string) => void;
  onBack: () => void;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}

function heat(char: string, confidence: number) {
  if (char === "?") return "slot-hatched";
  if (confidence >= 0.85) return "bg-emerald-200 text-emerald-950";
  if (confidence >= 0.7) return "bg-emerald-100 text-emerald-900";
  if (confidence >= 0.55) return "bg-amber-100 text-amber-900";
  return "bg-rose-100 text-rose-900";
}

export default function VehicleInspector({ caseId, vehicleId, vehicles, onOpenVehicle, onBack, onChanged, onError }: Props) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [frameIndex, setFrameIndex] = useState(0);
  const [selectedSlot, setSelectedSlot] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [colour, setColour] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [rerank, setRerank] = useState<number | null>(null);

  useEffect(() => {
    setVehicle(null);
    setFailed(false);
    setFrameIndex(0);
    setSelectedSlot(null);
    setEdits({});
    setColour("");
    setBody("");
    setRerank(null);
    if (!vehicleId) return;
    let live = true;
    api.vehicle(caseId, vehicleId)
      .then((value) => { if (live) setVehicle(value); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [caseId, vehicleId, attempt]);

  const activeSlots = vehicle?.active_evidence.plate.slots ?? [];
  const slotCount = useMemo(() => Math.min(Math.max(activeSlots.length, vehicle?.fused_plate.slots.length ?? 0, 10), 12), [activeSlots.length, vehicle]);
  const position = vehicles.findIndex((item) => item.id === vehicleId);

  if (!vehicleId) return <div className="panel"><Empty title="No vehicle selected">Choose a track from the case results.</Empty></div>;
  if (failed) {
    return (
      <div className="panel"><Empty title="Could not load this track">
        <button className="btn mt-2" onClick={() => setAttempt(attempt + 1)}>Retry</button>
      </Empty></div>
    );
  }
  if (!vehicle) return <div className="panel"><Empty title="Loading vehicle evidence…" /></div>;

  const keyframe = vehicle.keyframes[frameIndex];
  const fused = vehicle.fused_plate;
  const rejected = fused.rejected_reads ?? [];
  const slot = selectedSlot === null ? null : fused.slots[selectedSlot];
  const hasEdits = Object.keys(edits).length > 0 || Boolean(colour) || Boolean(body);
  const model = vehicle.attributes.make_model;

  const apply = async (reset = false) => {
    setSaving(true);
    try {
      const response = await api.override(caseId, vehicle.id, reset ? { reset: true } : {
        slots: Object.entries(edits).filter(([, char]) => char).map(([index, char]) => ({ position: Number(index), char })),
        colour: colour || undefined,
        body_type: body || undefined,
      });
      setVehicle(response.vehicle);
      setRerank(response.rerank_ms);
      setEdits({});
      setColour("");
      setBody("");
      await onChanged();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" onClick={onBack}><ArrowLeft size={16} /> Results</button>
        <span className="flex">
          <button className="btn" aria-label="Previous track" disabled={position <= 0} onClick={() => onOpenVehicle(vehicles[position - 1].id)}><ChevronLeft size={16} /></button>
          <button className="btn -ml-px" aria-label="Next track" disabled={position < 0 || position >= vehicles.length - 1} onClick={() => onOpenVehicle(vehicles[position + 1].id)}><ChevronRight size={16} /></button>
        </span>
        <span className="text-xs font-semibold">{vehicle.camera_label} · Track {vehicle.track_id}</span>
        <PlateText text={vehicle.match_result.query_plate} />
        <OutcomeBadge outcome={vehicle.match_result.outcome} long />
        <LinkBadge status={vehicle.link_status} />
        {vehicle.overridden && <Badge tone="amber">Investigator verified</Badge>}
        {vehicle.attributes.partial_view && <Badge>Partial view</Badge>}
      </div>

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,4fr)_minmax(0,5fr)_minmax(0,4fr)]">
        <section className="panel min-w-0">
          <div className="panel-head">Frame evidence</div>
          {keyframe ? (
            <div className="space-y-2 p-2">
              <img src={artifactUrl(keyframe.frame)} alt={`Annotated frame at ${keyframe.timestamp_sec} seconds`} className="max-h-[420px] w-full border border-line bg-slate-900 object-contain" />
              <div className="num flex flex-wrap justify-between gap-x-2 text-2xs text-muted"><span>{seconds(keyframe.timestamp_sec)} · frame {keyframe.frame_idx}</span><span>sharpness {keyframe.sharpness.toFixed(0)}</span></div>
              <div className="flex gap-1 overflow-x-auto">
                {vehicle.keyframes.map((frame, index) => (
                  <button key={frame.frame} onClick={() => setFrameIndex(index)} aria-label={`Show frame ${frame.frame_idx}`} aria-pressed={index === frameIndex} className={`h-11 w-16 shrink-0 border ${index === frameIndex ? "border-2 border-navy" : "border-line"}`}>
                    <img src={artifactUrl(frame.crop)} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
              {keyframe.plate_raw ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <figure><figcaption className="label mb-0.5">Raw crop (source)</figcaption><img src={artifactUrl(keyframe.plate_raw)} alt="Raw plate crop" className="h-14 w-full border border-line bg-slate-100 object-contain [image-rendering:pixelated]" /></figure>
                    <figure><figcaption className="label mb-0.5">Enhanced view</figcaption><img src={artifactUrl(keyframe.plate_enhanced)} alt="Enhanced plate crop" className="h-14 w-full border border-line bg-slate-100 object-contain" /></figure>
                  </div>
                  <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-2 text-2xs text-muted">
                    <dt>Plate box</dt><dd className="num">{((keyframe.plate_box_confidence ?? 0) * 100).toFixed(0)}% · {keyframe.plate_crop_size?.join("×")} px</dd>
                    <dt>Frame quality</dt><dd className="num">sharpness {keyframe.frame_sharpness?.toFixed(0)} · brightness {keyframe.brightness?.toFixed(0)}{keyframe.low_sharpness ? " · low sharpness" : ""}</dd>
                    <dt>OCR engine</dt><dd className="num break-words">{keyframe.ocr_engine}</dd>
                    <dt>Perspective</dt><dd>{keyframe.rectification?.reason ?? "not recorded"}</dd>
                    <dt>Raw hash</dt><dd className="num truncate" title={keyframe.crop_sha256}>{keyframe.crop_sha256?.slice(0, 16)}…</dd>
                  </dl>
                  {keyframe.variants && (
                    <details>
                      <summary className="cursor-pointer text-xs font-medium">OCR by image variant <span className="num font-normal text-muted">{keyframe.variants.length}</span></summary>
                      <ul className="mt-1 divide-y divide-line border border-line">
                        {keyframe.variants.map((view) => (
                          <li key={view.name} className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-2 p-1.5">
                            <img src={artifactUrl(view.image)} alt={view.label} loading="lazy" className="h-8 w-[88px] border border-line bg-slate-100 object-contain" />
                            <span className="min-w-0 text-2xs">
                              <span className="block font-medium">{view.label} <span className="font-normal text-muted">· {view.kind}</span></span>
                              <span className="num block truncate text-muted">{view.text || "no read"} · {(view.mean_confidence * 100).toFixed(0)}%</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                      <p className="mt-1 text-2xs text-muted">Only the raw crop is source evidence. Other views cannot establish a character alone.</p>
                    </details>
                  )}
                </div>
              ) : <div className="border border-line px-2 py-1.5 text-2xs text-muted">No plate belonging to this vehicle was found in this frame.</div>}
              {fused.stack_crop && (
                <figure><figcaption className="label mb-0.5">Multi-frame stack (aligned real pixels)</figcaption><img src={artifactUrl(fused.stack_crop)} alt="Multi-frame plate stack" className="h-14 w-full border border-line bg-slate-100 object-contain" /></figure>
              )}
            </div>
          ) : <Empty title="No keyframes stored" />}
          <dl className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-2 gap-y-1 border-t border-line p-3 text-xs">
            <dt className="label">Colour</dt><dd>{vehicle.attributes.colours.map((c) => `${c.label} ${(c.confidence * 100).toFixed(0)}%`).join(", ") || "Unknown"}</dd>
            <dt className="label">Body</dt><dd>{(vehicle.attributes.body_type.distribution?.length ? vehicle.attributes.body_type.distribution.slice(0, 2) : [vehicle.attributes.body_type]).map((b) => `${pretty(b.label)} ${(b.confidence * 100).toFixed(0)}%`).join(", ")}{vehicle.attributes.body_type.source?.includes("uncertain") ? " (fine type uncertain)" : ""}</dd>
            <dt className="label">Make/model</dt><dd>{model.status === "recognised" ? `Estimated ${model.predictions[0].make} ${model.predictions[0].model}` : "Unknown"}</dd>
            <dt className="label">Tracked</dt><dd className="num">{vehicle.frames_tracked} frames{(vehicle.attributes.merged_track_ids?.length ?? 0) > 0 ? ` · ${vehicle.attributes.merged_track_ids!.length} fragment(s) merged` : ""}</dd>
          </dl>
          <p className="border-t border-line px-3 py-2 text-2xs text-muted">Attribute estimates are supporting evidence only and never identify a vehicle.</p>
        </section>

        <section className="panel min-w-0">
          <div className="panel-head">Multi-frame plate recovery <span className="num font-normal text-muted">{fused.reads_used ?? 0} used · {fused.reads_rejected ?? 0} rejected</span></div>
          {vehicle.plate_format === "non_latin_digits" && (
            <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-2xs text-amber-900">This clip is marked non-Latin, so letters are withheld and only digits are used.</div>
          )}
          {fused.matrix.length ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-mono text-2xs">
                <thead><tr><th className="th sticky left-0 z-10">Time</th>{fused.slots.map((item) => <th key={item.position} className="th text-center">{item.position + 1}</th>)}</tr></thead>
                <tbody>
                  {fused.matrix.map((row) => (
                    <tr key={`${row.frame_idx}-${row.timestamp_sec}`}>
                      <td className="td sticky left-0 z-10 whitespace-nowrap bg-white text-muted">{row.derived ? "stack" : seconds(row.timestamp_sec)}</td>
                      {row.cells.map((cell, index) => (
                        <td key={index} title={`${(cell.confidence * 100).toFixed(1)}%`} className={`h-6 min-w-[24px] border border-white text-center font-semibold ${heat(cell.char, cell.confidence)}`}>{cell.char}</td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <th className="th sticky left-0 z-10">Fused</th>
                    {fused.slots.map((item) => (
                      <td key={item.position} className="border border-white p-0">
                        <button aria-label={`Show evidence for slot ${item.position + 1}`} aria-pressed={selectedSlot === item.position} onClick={() => setSelectedSlot(selectedSlot === item.position ? null : item.position)}
                          className={`h-7 w-full min-w-[24px] text-xs font-semibold ${heat(item.char, item.confidence)} ${selectedSlot === item.position ? "outline outline-2 -outline-offset-2 outline-navy" : ""}`}>{item.char}</button>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          ) : <Empty title="No usable plate reads">No character is inferred when a plate cannot be read.</Empty>}
          {slot ? (
            <div className="border-t border-line px-3 py-2 text-2xs text-muted">
              <div className="mb-1 font-semibold text-ink">Slot {slot.position + 1}: {slot.char === "?" ? "unknown" : slot.char} · fused {(slot.confidence * 100).toFixed(0)}% · {slot.support_frames} of {slot.observed_frames} frame(s) agree · {slot.source_supported_frames ?? 0} from source pixels</div>
              {slot.unknown_reason && <div className="mb-1 text-amber-800">Unknown because {slot.unknown_reason}.</div>}
              {slot.candidates.length > 0 && <div>Alternatives: <span className="num">{slot.candidates.map((c) => `${c.char} ${(c.probability * 100).toFixed(0)}%`).join(", ")}</span></div>}
              <ul className="mt-1 max-h-52 divide-y divide-line overflow-y-auto border border-line">
                {(slot.evidence ?? []).map((vote, index) => (
                  <li key={`${vote.frame_idx}-${index}`} className="flex items-center gap-2 p-1">
                    {vote.crop ? <img src={artifactUrl(vote.crop)} alt={`Raw crop from frame ${vote.frame_idx}`} loading="lazy" className="h-6 w-16 shrink-0 border border-line object-contain" /> : <span className="h-6 w-16 shrink-0 border border-line bg-canvas text-center leading-6">stack</span>}
                    <span className="min-w-0">
                      <span className="num block text-ink">{vote.frame_idx < 0 ? "stack" : `frame ${vote.frame_idx} · ${seconds(vote.timestamp_sec)}`} · {vote.char} {(vote.confidence * 100).toFixed(0)}%{vote.source_supported === false ? " · not in source" : ""}</span>
                      {vote.variants && vote.variants.length > 0 && <span className="num block truncate">{vote.variants.map((v) => `${v.variant}:${v.char}`).join(" ")}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : fused.slots.length > 0 && <div className="border-t border-line px-3 py-1.5 text-2xs text-muted">Select a fused character to see its frames, crops, variants and alternatives.</div>}
          {rejected.length > 0 && (
            <details className="border-t border-line">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Rejected reads <span className="num font-normal text-muted">{rejected.length}</span></summary>
              <ul className="max-h-40 divide-y divide-line overflow-y-auto px-3 pb-2 text-2xs text-muted">
                {rejected.map((read, index) => <li key={index} className="py-1"><span className="num text-ink">{read.raw_text}</span> · {read.frame_idx < 0 ? "stack" : seconds(read.timestamp_sec)} · {read.reason}</li>)}
              </ul>
            </details>
          )}
          <div className="space-y-2 border-t border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold">Investigator override</span>
              {rerank !== null && <span className="num text-2xs text-muted">Re-ranked in {rerank.toFixed(1)} ms</span>}
            </div>
            <div className="flex flex-wrap gap-px">
              {Array.from({ length: slotCount }, (_, index) => {
                const current = activeSlots[index];
                const locked = current?.locked;
                return (
                  <input
                    key={index}
                    aria-label={`Plate slot ${index + 1}`}
                    maxLength={1}
                    value={edits[index] ?? (current && current.char !== "?" ? current.char : "")}
                    placeholder="?"
                    onChange={(event) => setEdits({ ...edits, [index]: event.target.value.toUpperCase().replace(/[^A-Z0-9?]/g, "") })}
                    className={`h-8 w-7 border text-center font-mono text-xs font-semibold uppercase ${edits[index] !== undefined ? "border-navy bg-navy-tint" : locked ? "border-amber-400 bg-amber-50" : "border-line"}`}
                  />
                );
              })}
            </div>
            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
              <select aria-label="Verified colour" className="field" value={colour} onChange={(e) => setColour(e.target.value)}>
                <option value="">Colour: {vehicle.overrides.colour ?? "AI value"}</option>
                {COLOURS.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
              <select aria-label="Verified body type" className="field" value={body} onChange={(e) => setBody(e.target.value)}>
                <option value="">Body: {vehicle.overrides.body_type ? pretty(vehicle.overrides.body_type) : "AI value"}</option>
                {BODY_TYPES.map((value) => <option key={value} value={value}>{pretty(value)}</option>)}
              </select>
              <button className="btn btn-primary" disabled={!hasEdits || saving} onClick={() => apply()}>Verify and re-rank</button>
              <button className="btn" aria-label="Reset overrides" title="Reset to AI evidence" disabled={!vehicle.overridden || saving} onClick={() => apply(true)}><RotateCcw size={16} /></button>
            </div>
          </div>
        </section>

        <section className="panel min-w-0">
          <div className="panel-head">Registry matching</div>
          <Shortlist key={`${vehicle.id}-${JSON.stringify(vehicle.overrides)}`} result={vehicle.match_result} />
        </section>
      </div>
    </div>
  );
}
