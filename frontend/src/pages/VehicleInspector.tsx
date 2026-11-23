import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { ZoomImage } from "../components/ZoomImage";
import { Badge, Empty, LinkBadge, Notice, OutcomeBadge, PlateText, pretty, seconds } from "../components/ui";
import { BODY_TYPES, COLOURS, type CaseCounts, type VehicleDetail, type VehicleSummary } from "../types";

interface Props {
  caseId: string;
  vehicleId: string | null;
  vehicles: VehicleSummary[];
  onOpenVehicle: (id: string) => void;
  onBack: () => void;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
  formatHints?: CaseCounts["format_hints"];
}

const KIND_LABELS: Record<string, string> = { source: "source", geometric: "geometric", interpolated: "interpolated", filtered: "filtered" };
const BANDS = [
  { label: "≥ .85", className: "bg-emerald-200 text-emerald-950" },
  { label: ".70–.84", className: "bg-emerald-100 text-emerald-900" },
  { label: ".55–.69", className: "bg-amber-100 text-amber-900" },
  { label: "< .55", className: "bg-rose-100 text-rose-900" },
];

function heat(char: string, confidence: number) {
  if (char === "?") return "slot-hatched";
  if (confidence >= 0.85) return BANDS[0].className;
  if (confidence >= 0.7) return BANDS[1].className;
  if (confidence >= 0.55) return BANDS[2].className;
  return BANDS[3].className;
}

const decimal = (value: number) => (value >= 1 ? "1.0" : value.toFixed(2).replace(/^0/, ""));

export default function VehicleInspector({ caseId, vehicleId, vehicles, onOpenVehicle, onBack, onChanged, onError, formatHints = [] }: Props) {
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

  if (!vehicleId) return <div className="panel"><Empty title="No vehicle selected">Choose a track from the case workspace.<div><button className="btn mt-2" onClick={onBack}>Open case workspace</button></div></Empty></div>;
  if (failed) {
    return (
      <div role="alert" className="panel"><Empty title="Could not load this track">
        <button className="btn mt-2" onClick={() => setAttempt(attempt + 1)}>Retry</button>
      </Empty></div>
    );
  }
  if (!vehicle) return <div role="status" className="panel"><Empty title="Loading vehicle evidence…" /></div>;

  const keyframe = vehicle.keyframes[frameIndex];
  const fused = vehicle.fused_plate;
  const rejected = fused.rejected_reads ?? [];
  const slot = selectedSlot === null ? null : fused.slots[selectedSlot];
  const hasEdits = Object.keys(edits).length > 0 || Boolean(colour) || Boolean(body);
  const model = vehicle.attributes.make_model;
  const quality = vehicle.attributes.track_quality;
  const inspection = quality?.plate_inspection;
  const crop = keyframe?.plate_crop_size ? `${keyframe.plate_crop_size[0]}×${keyframe.plate_crop_size[1]} px` : "";
  const coverage = vehicle.match_result.registry_coverage;
  const sourceContext = keyframe ? { frame: artifactUrl(keyframe.frame), label: `${vehicle.camera_label} · T${vehicle.track_id} · ${seconds(keyframe.timestamp_sec)} · frame ${keyframe.frame_idx}` } : undefined;
  const transformed = keyframe?.variants?.filter((view) => view.name !== "raw") ?? [];
  const rawVariant = keyframe?.variants?.find((view) => view.name === "raw");

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
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" onClick={onBack}><ArrowLeft size={15} /> Case workspace</button>
          <span className="flex">
            <button className="btn rounded-r-none" aria-label="Previous track" disabled={position <= 0} onClick={() => onOpenVehicle(vehicles[position - 1].id)}><ChevronLeft size={16} /></button>
            <button className="btn -ml-px rounded-l-none" aria-label="Next track" disabled={position < 0 || position >= vehicles.length - 1} onClick={() => onOpenVehicle(vehicles[position + 1].id)}><ChevronRight size={16} /></button>
          </span>
          {position >= 0 && <span className="num text-2xs text-muted">{position + 1} of {vehicles.length}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <div>
            <div className="text-2xs font-semibold uppercase tracking-wide text-accent-soft">Vehicle inspector</div>
            <h1 className="text-xl font-semibold tracking-tight">{vehicle.camera_label} · <span className="num">Track {vehicle.track_id}</span></h1>
          </div>
          <PlateText text={vehicle.match_result.query_plate} size="lg" />
          <span className="flex flex-wrap items-center gap-1">
            <OutcomeBadge outcome={vehicle.match_result.outcome} long />
            <LinkBadge status={vehicle.link_status} />
            {vehicle.clip.synthetic && <Badge tone="amber">Demo evidence</Badge>}
            {vehicle.overridden && <Badge tone="amber">Investigator verified</Badge>}
            {vehicle.attributes.partial_view && <Badge>Partial view</Badge>}
            {quality && <Badge tone={quality.tier === "reliable" ? "slate" : "amber"} title={quality.reasons.join("; ")}>{quality.tier === "reliable" ? "Reliable track" : "Track needs review"}</Badge>}
          </span>
        </div>
      </header>

      {vehicle.match_result.outcome === "NO_REGISTRY_COVERAGE" && coverage && (
        <Notice icon={<AlertTriangle size={15} />} title="Registry not searched">
          This camera uses a plate format with {coverage.compatible_records} compatible records out of {coverage.total_records.toLocaleString()}. The read is kept as OCR evidence and is not a no-match result.
        </Notice>
      )}

      {vehicle.match_result.outcome === "NO_REGISTRY_MATCH" && formatHints.filter((hint) => hint.clip_id === vehicle.clip_id).map((hint) => (
        <Notice key={hint.family} icon={<AlertTriangle size={15} />} title="Possible format gap">{hint.message}</Notice>
      ))}

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,7fr)_minmax(340px,4fr)]">
        <div className="min-w-0 space-y-3">
          <section className="panel" aria-labelledby="source-frame">
            <div className="panel-head">
              <h2 id="source-frame">Annotated source frame</h2>
              {keyframe && <span className="num font-normal text-muted">{seconds(keyframe.timestamp_sec)} · frame {keyframe.frame_idx} · sharpness {keyframe.sharpness.toFixed(0)}</span>}
            </div>
            {keyframe ? (
              <div className="space-y-2 p-2">
                <img src={artifactUrl(keyframe.frame)} alt={`Annotated frame at ${keyframe.timestamp_sec} seconds with track ${vehicle.track_id} outlined`} className="max-h-[560px] w-full rounded-evidence bg-shell object-contain" />
                <div className="flex gap-1 overflow-x-auto pb-0.5" role="group" aria-label="Keyframes">
                  {vehicle.keyframes.map((frame, index) => (
                    <button key={frame.frame} onClick={() => setFrameIndex(index)} aria-label={`Show frame ${frame.frame_idx} at ${frame.timestamp_sec} seconds`} aria-pressed={index === frameIndex}
                      className={`w-20 shrink-0 overflow-hidden rounded-evidence border text-left ${index === frameIndex ? "border-accent ring-1 ring-accent-soft" : "border-line"}`}>
                      <img src={artifactUrl(frame.crop)} alt="" className="h-12 w-full object-cover" />
                      <span className="num block bg-surface px-1 text-2xs text-muted">{seconds(frame.timestamp_sec)}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : <Empty title="No keyframes stored" />}
          </section>

          <section className="panel" aria-labelledby="plate-images">
            <div className="panel-head"><h2 id="plate-images">Plate crop and transformed views</h2>{crop && <span className="num font-normal text-muted">source {crop}</span>}</div>
            {keyframe?.plate_raw ? (
              <div className="space-y-2 p-2">
                <div className="grid gap-2 sm:grid-cols-2">
                  <ZoomImage src={artifactUrl(keyframe.plate_raw)} alt="Raw plate crop" title="Raw crop (source evidence)" detail={`${crop} · frame ${keyframe.frame_idx} · ${seconds(keyframe.timestamp_sec)}`} source={sourceContext} />
                  <ZoomImage src={artifactUrl(keyframe.plate_enhanced)} alt="Enhanced plate crop" title="Grayscale + CLAHE (viewing aid)" detail="Adds no source detail" source={sourceContext} />
                </div>
                <p className="rounded-evidence border border-line bg-canvas px-2 py-1 text-2xs text-muted">Enhanced and interpolated views aid inspection. They cannot establish details absent from the source footage, so only the raw crop is source evidence.</p>
                {(keyframe.image_warnings?.length ?? 0) > 0 && (
                  <ul className="space-y-0.5 rounded-evidence border border-amber-300 bg-amber-50 px-2 py-1 text-2xs text-amber-950">
                    {keyframe.image_warnings!.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                )}
                {transformed.length > 0 && (
                  <div>
                    <h3 className="mb-1 text-2xs font-semibold text-muted">OCR by image view{rawVariant ? <> · raw read <span className="num text-ink">{rawVariant.text || "none"}</span></> : null}</h3>
                    <ul className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 2xl:grid-cols-4">
                      {transformed.map((view) => (
                        <li key={view.name} className="min-w-0 rounded-evidence border border-line p-1.5">
                          <ZoomImage compact src={artifactUrl(view.image)} alt={view.label} title={view.label} detail={view.width ? `${view.width}×${view.height} px · ${KIND_LABELS[view.kind] ?? view.kind}` : KIND_LABELS[view.kind] ?? view.kind} source={sourceContext} />
                          <div className="num mt-0.5 truncate text-2xs" title={view.ocr_read === false ? "OCR skipped because the core views agreed" : undefined}>{view.ocr_read === false ? <span className="text-muted">not read, core views agreed</span> : <>{view.text || "no read"} <span className="text-muted">{decimal(view.mean_confidence)}</span></>}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <dl className="grid gap-x-4 gap-y-0.5 text-2xs text-muted sm:grid-cols-2">
                  <div className="flex justify-between gap-2"><dt>Plate box confidence</dt><dd className="num">{decimal(keyframe.plate_box_confidence ?? 0)}</dd></div>
                  {keyframe.plate_box_source && <div className="flex justify-between gap-2"><dt>Source box</dt><dd className="num">{keyframe.plate_box_source.join(", ")}</dd></div>}
                  <div className="flex justify-between gap-2"><dt>Frame quality</dt><dd className="num">sharp {keyframe.frame_sharpness?.toFixed(0)} · bright {keyframe.brightness?.toFixed(0)}{keyframe.low_sharpness ? " · low" : ""}</dd></div>
                  <div className="flex justify-between gap-2"><dt>Perspective</dt><dd className="text-right">{keyframe.rectification?.reason ?? "not recorded"}</dd></div>
                  <div className="flex justify-between gap-2"><dt>OCR engine</dt><dd className="num truncate" title={keyframe.ocr_engine}>{keyframe.ocr_engine}</dd></div>
                  <div className="flex justify-between gap-2"><dt>Raw crop SHA-256</dt><dd className="num truncate" title={keyframe.crop_sha256}>{keyframe.crop_sha256?.slice(0, 16)}…</dd></div>
                </dl>
                {fused.stack_crop && <div className="max-w-sm"><ZoomImage compact src={artifactUrl(fused.stack_crop)} alt="Multi-frame plate stack" title="Multi-frame stack (aligned real pixels, not an independent read)" source={sourceContext} /></div>}
              </div>
            ) : <div className="p-3 text-2xs text-muted">No plate belonging to this vehicle was found in this frame.</div>}
          </section>

          <section className="panel" aria-labelledby="recovery">
            <div className="panel-head"><h2 id="recovery">Multi-frame plate recovery</h2><span className="num font-normal text-muted">{fused.reads_used ?? 0} used · {fused.reads_rejected ?? 0} rejected</span></div>
            {vehicle.plate_format === "non_latin_digits" && (
              <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-2xs text-amber-950">This clip is marked non-Latin, so letters are withheld and only digits are used.</div>
            )}
            {fused.matrix.length ? (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse font-mono text-2xs">
                    <caption className="sr-only">Characters read per frame, with the fused result</caption>
                    <thead><tr><th scope="col" className="th sticky left-0 z-10">Time</th>{fused.slots.map((item) => <th scope="col" key={item.position} className="th text-center">{item.position + 1}</th>)}</tr></thead>
                    <tbody>
                      {fused.matrix.map((row) => (
                        <tr key={`${row.frame_idx}-${row.timestamp_sec}`}>
                          <th scope="row" className="td sticky left-0 z-10 whitespace-nowrap bg-surface text-left font-normal text-muted">{row.derived ? "stack" : seconds(row.timestamp_sec)}</th>
                          {row.cells.map((cell, index) => (
                            <td key={index} title={`Confidence ${decimal(cell.confidence)}`} className={`h-6 min-w-[26px] border border-surface text-center font-semibold ${heat(cell.char, cell.confidence)}`}>{cell.char}</td>
                          ))}
                        </tr>
                      ))}
                      <tr>
                        <th scope="row" className="th sticky left-0 z-10">Fused</th>
                        {fused.slots.map((item) => (
                          <td key={item.position} className="border border-surface p-0">
                            <button aria-label={`Show evidence for slot ${item.position + 1}, ${item.char === "?" ? "unknown" : item.char}`} aria-pressed={selectedSlot === item.position} onClick={() => setSelectedSlot(selectedSlot === item.position ? null : item.position)}
                              className={`h-8 w-full min-w-[26px] text-xs font-semibold ${heat(item.char, item.confidence)} ${selectedSlot === item.position ? "outline outline-2 -outline-offset-2 outline-accent-soft" : ""}`}>{item.char}</button>
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <th scope="row" className="td sticky left-0 z-10 bg-surface text-left font-normal text-muted">Conf.</th>
                        {fused.slots.map((item) => <td key={item.position} className="td px-0 text-center text-muted">{item.char === "?" ? "–" : decimal(item.confidence)}</td>)}
                      </tr>
                      <tr>
                        <th scope="row" className="td sticky left-0 z-10 bg-surface text-left font-normal text-muted">Alt.</th>
                        {fused.slots.map((item) => <td key={item.position} className="td px-0 text-center text-muted">{item.candidates[0]?.char ?? ""}</td>)}
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-3 py-1.5 text-2xs text-muted">
                  <span className="font-medium text-ink">OCR confidence</span>
                  {BANDS.map((band) => <span key={band.label} className="inline-flex items-center gap-1"><span className={`num px-1 ${band.className}`}>A</span>{band.label}</span>)}
                  <span className="inline-flex items-center gap-1"><span className="slot-hatched num px-1">?</span>unknown</span>
                  <span>Alternatives are shown for review and never fill a slot.</span>
                </div>
              </>
            ) : <Empty title="No usable plate reads">No character is inferred when a plate cannot be read.</Empty>}
            {slot ? (
              <div className="border-t border-line px-3 py-2 text-2xs text-muted">
                <div className="mb-1 font-semibold text-ink">Slot {slot.position + 1}: {slot.char === "?" ? "unknown" : slot.char} · fused {decimal(slot.confidence)} · {slot.support_frames} of {slot.observed_frames} frame(s) agree · {slot.source_supported_frames ?? 0} from source pixels</div>
                {slot.unknown_reason && <div className="mb-1 text-amber-900">Unknown because {slot.unknown_reason}.</div>}
                {slot.candidates.length > 0 && <div>Alternatives: <span className="num">{slot.candidates.map((c) => `${c.char} ${decimal(c.probability)}`).join(", ")}</span></div>}
                <ul className="mt-1 max-h-52 divide-y divide-line overflow-y-auto rounded-evidence border border-line">
                  {(slot.evidence ?? []).map((vote, index) => (
                    <li key={`${vote.frame_idx}-${index}`} className="flex items-center gap-2 p-1">
                      {vote.crop ? <img src={artifactUrl(vote.crop)} alt={`Raw crop from frame ${vote.frame_idx}`} loading="lazy" className="h-7 w-20 shrink-0 border border-line object-contain" /> : <span className="h-7 w-20 shrink-0 border border-line bg-canvas text-center leading-7">stack</span>}
                      <span className="min-w-0">
                        <span className="num block text-ink">{vote.frame_idx < 0 ? "stack" : `frame ${vote.frame_idx} · ${seconds(vote.timestamp_sec)}`} · {vote.char} {decimal(vote.confidence)}{vote.source_supported === false ? " · not in source" : ""}</span>
                        {vote.variants && vote.variants.length > 0 && <span className="num block truncate">{vote.variants.map((v) => `${v.variant}:${v.char}`).join(" ")}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : fused.slots.length > 0 && <div className="border-t border-line px-3 py-1.5 text-2xs text-muted">Select a fused character to see its frames, crops, variants and alternatives.</div>}
            {rejected.length > 0 && (
              <div className="border-t border-line">
                <h3 className="px-3 py-1.5 text-xs font-semibold">Rejected reads <span className="num font-normal text-muted">{rejected.length}</span></h3>
                <div className="max-h-44 overflow-auto">
                  <table className="w-full min-w-[420px] border-collapse text-2xs">
                    <thead><tr><th scope="col" className="th">Read</th><th scope="col" className="th">Time</th><th scope="col" className="th">Why it was rejected</th></tr></thead>
                    <tbody>{rejected.map((read, index) => (
                      <tr key={index}><td className="td num font-semibold">{read.raw_text}</td><td className="td num whitespace-nowrap text-muted">{read.frame_idx < 0 ? "stack" : seconds(read.timestamp_sec)}</td><td className="td text-muted">{read.reason}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        </div>

        <div className="min-w-0 space-y-3">
          <section className="panel" aria-labelledby="registry-match">
            <div className="panel-head"><h2 id="registry-match">Registry matching</h2><span className="font-normal text-muted">Scores are not probabilities</span></div>
            <Shortlist key={`${vehicle.id}-${JSON.stringify(vehicle.overrides)}`} result={vehicle.match_result} />
          </section>

          <section className="panel" aria-labelledby="override">
            <div className="panel-head"><h2 id="override">Investigator override</h2>{rerank !== null && <span className="num font-normal text-muted">Re-ranked in {rerank.toFixed(1)} ms</span>}</div>
            <div className="space-y-2 p-3">
              <p className="text-2xs text-muted">Enter only what you verified in the source footage. AI evidence stays stored and the change is written to the audit log.</p>
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
                      className={`h-8 w-7 border text-center font-mono text-xs font-semibold uppercase placeholder:text-slate-500 ${edits[index] !== undefined ? "border-accent bg-accent-tint" : locked ? "border-amber-400 bg-amber-50" : "border-line"}`}
                    />
                  );
                })}
              </div>
              <div className="grid gap-1.5 sm:grid-cols-2">
                <select aria-label="Verified colour" className="field" value={colour} onChange={(e) => setColour(e.target.value)}>
                  <option value="">Colour: {vehicle.overrides.colour ?? "AI value"}</option>
                  {COLOURS.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
                <select aria-label="Verified body type" className="field" value={body} onChange={(e) => setBody(e.target.value)}>
                  <option value="">Body: {vehicle.overrides.body_type ? pretty(vehicle.overrides.body_type) : "AI value"}</option>
                  {BODY_TYPES.map((value) => <option key={value} value={value}>{pretty(value)}</option>)}
                </select>
              </div>
              <div className="flex gap-1.5">
                <button className="btn btn-primary flex-1" disabled={!hasEdits || saving} onClick={() => apply()}>Verify and re-rank</button>
                <button className="btn" aria-label="Reset overrides" title="Reset to AI evidence" disabled={!vehicle.overridden || saving} onClick={() => apply(true)}><RotateCcw size={15} /></button>
              </div>
            </div>
          </section>

          <section className="panel" aria-labelledby="attributes">
            <div className="panel-head"><h2 id="attributes">Vehicle attributes</h2><span className="font-normal text-muted">Supporting only</span></div>
            <dl className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-2 gap-y-1 p-3 text-xs">
              <dt className="label">Colour</dt><dd>{vehicle.attributes.colours.map((c) => `${c.label} ${decimal(c.confidence)}`).join(", ") || "Unknown"}</dd>
              <dt className="label">Body</dt><dd>{(vehicle.attributes.body_type.distribution?.length ? vehicle.attributes.body_type.distribution.slice(0, 2) : [vehicle.attributes.body_type]).map((b) => `${pretty(b.label)} ${decimal(b.confidence)}`).join(", ")}{vehicle.attributes.body_type.source?.includes("uncertain") ? " (fine type uncertain)" : ""}</dd>
              <dt className="label">Make/model</dt><dd>{model.status === "recognised" ? `Estimated ${model.predictions[0].make} ${model.predictions[0].model}` : "Unknown"}</dd>
              <dt className="label">Tracked</dt><dd className="num">{seconds(vehicle.first_seen_sec)}–{seconds(vehicle.last_seen_sec)} · {vehicle.frames_tracked} frames{(vehicle.attributes.merged_track_ids?.length ?? 0) > 0 ? ` · ${vehicle.attributes.merged_track_ids!.length} merged` : ""}</dd>
            </dl>
            <p className="border-t border-line px-3 py-2 text-2xs text-muted">Attribute estimates never identify a vehicle.</p>
            {quality && (
              <details className="border-t border-line">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Track quality <span className="font-normal text-muted">{quality.tier === "reliable" ? "reliable" : "needs review"}</span></summary>
                <div className="space-y-1.5 px-3 pb-2 text-2xs text-muted">
                  {quality.reasons.length > 0 && <ul className="list-disc pl-4 text-amber-900">{quality.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
                  <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3">
                    <dt>Duration</dt><dd className="num">{quality.duration_sec.toFixed(2)} s</dd>
                    <dt>Sampled frames</dt><dd className="num">{quality.sampled_frames}</dd>
                    <dt>Best-frame sharpness</dt><dd className="num">{quality.best_frame_sharpness.toFixed(0)}</dd>
                    <dt>Mean detector confidence</dt><dd className="num">{decimal(quality.mean_detector_confidence)}</dd>
                    {inspection && <>
                      <dt>Frames inspected for a plate</dt><dd className="num">{inspection.frames_inspected} of {inspection.candidate_frames}</dd>
                      <dt>Plate reads kept</dt><dd className="num">{inspection.plates_read}</dd>
                      <dt>Near-duplicate frames skipped</dt><dd className="num">{inspection.near_duplicates_skipped}</dd>
                      <dt>Skipped, plate already stable</dt><dd className="num">{inspection.skipped_plate_already_stable}</dd>
                      <dt>Skipped, no plate in best frames</dt><dd className="num">{inspection.skipped_no_plate_in_best_frames}</dd>
                    </>}
                  </dl>
                  {inspection && Object.keys(inspection.rejections).length > 0 && (
                    <div><span className="font-medium text-ink">Frames without a usable plate</span>
                      <ul className="list-disc pl-4">{Object.entries(inspection.rejections).map(([reason, count]) => <li key={reason}>{reason}: <span className="num">{count}</span></li>)}</ul>
                    </div>
                  )}
                </div>
              </details>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
