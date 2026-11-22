import { ArrowLeft, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Badge, Empty, PlateText, pretty, seconds } from "../components/ui";
import { BODY_TYPES, COLOURS, type VehicleDetail } from "../types";

interface Props {
  caseId: string;
  vehicleId: string | null;
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

export default function VehicleInspector({ caseId, vehicleId, onBack, onChanged, onError }: Props) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [colour, setColour] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [rerank, setRerank] = useState<number | null>(null);

  useEffect(() => {
    setVehicle(null);
    setFrameIndex(0);
    setEdits({});
    setColour("");
    setBody("");
    setRerank(null);
    if (!vehicleId) return;
    let live = true;
    api.vehicle(caseId, vehicleId).then((value) => live && setVehicle(value)).catch((error) => onError(error.message));
    return () => { live = false; };
  }, [caseId, vehicleId, onError]);

  const activeSlots = vehicle?.active_evidence.plate.slots ?? [];
  const slotCount = useMemo(() => Math.max(activeSlots.length, vehicle?.fused_plate.slots.length ?? 0, 10), [activeSlots.length, vehicle]);

  if (!vehicleId) return <div className="panel"><Empty title="No vehicle selected">Choose a detected vehicle from the case workspace.</Empty></div>;
  if (!vehicle) return <div className="panel"><Empty title="Loading vehicle evidence" /></div>;

  const keyframe = vehicle.keyframes[frameIndex];
  const fused = vehicle.fused_plate;
  const hasEdits = Object.keys(edits).length > 0 || Boolean(colour) || Boolean(body);

  const apply = async (reset = false) => {
    setSaving(true);
    try {
      const response = await api.override(caseId, vehicle.id, reset ? { reset: true } : {
        slots: Object.entries(edits).filter(([, char]) => char).map(([position, char]) => ({ position: Number(position), char })),
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
        <button className="btn" onClick={onBack}><ArrowLeft size={16} /> Vehicles</button>
        <span className="text-xs font-semibold">{vehicle.camera_label} · Track {vehicle.track_id}</span>
        <PlateText text={vehicle.match_result.query_plate} />
        {vehicle.overridden && <Badge tone="amber">Investigator verified</Badge>}
        {vehicle.entity_id && <Badge tone="navy">Cross-camera linked</Badge>}
      </div>

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,4fr)_minmax(0,5fr)_minmax(0,4fr)]">
        <section className="panel min-w-0">
          <div className="panel-head">Frame evidence</div>
          {keyframe ? (
            <div className="space-y-2 p-2">
              <img src={artifactUrl(keyframe.frame)} alt={`Annotated frame at ${keyframe.timestamp_sec} seconds`} className="w-full border border-line" />
              <div className="num flex justify-between text-2xs text-muted"><span>{seconds(keyframe.timestamp_sec)} · frame {keyframe.frame_idx}</span><span>sharpness {keyframe.sharpness}</span></div>
              <div className="flex gap-1 overflow-x-auto">
                {vehicle.keyframes.map((frame, index) => (
                  <button key={frame.frame} onClick={() => setFrameIndex(index)} aria-label={`Show frame ${frame.frame_idx}`} className={`h-11 w-16 shrink-0 border ${index === frameIndex ? "border-navy" : "border-line"}`}>
                    <img src={artifactUrl(frame.crop)} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
              {keyframe.plate_raw ? (
                <div className="grid grid-cols-2 gap-2">
                  <figure><figcaption className="label mb-0.5">Raw crop</figcaption><img src={artifactUrl(keyframe.plate_raw)} alt="Raw plate crop" className="h-14 w-full border border-line bg-slate-100 object-contain" /></figure>
                  <figure><figcaption className="label mb-0.5">Enhanced for OCR</figcaption><img src={artifactUrl(keyframe.plate_enhanced)} alt="Enhanced plate crop" className="h-14 w-full border border-line bg-slate-100 object-contain" /></figure>
                  <div className="num col-span-2 text-2xs text-muted">Read {keyframe.plate_text} · plate sharpness {keyframe.plate_sharpness} · {keyframe.ocr_source}</div>
                </div>
              ) : <div className="border border-line px-2 py-1.5 text-2xs text-muted">No plate was localized in this frame.</div>}
            </div>
          ) : <Empty title="No keyframes stored" />}
          <dl className="grid grid-cols-[84px_1fr] gap-x-2 gap-y-1 border-t border-line p-3 text-xs">
            <dt className="label">Colour</dt><dd>{vehicle.attributes.colours.map((c) => `${c.label} ${(c.confidence * 100).toFixed(0)}%`).join(", ") || "Unknown"}</dd>
            <dt className="label">Body</dt><dd>{pretty(vehicle.attributes.body_type.label)} {(vehicle.attributes.body_type.confidence * 100).toFixed(0)}%</dd>
            <dt className="label">Make/model</dt><dd>{vehicle.attributes.make_model.predictions.map((m) => m.make === "Unknown" ? "Unknown" : `${m.make} ${m.model} ${(m.confidence * 100).toFixed(0)}%`).join(", ")}</dd>
          </dl>
        </section>

        <section className="panel min-w-0">
          <div className="panel-head">Multi-frame plate recovery <span className="num font-normal text-muted">{fused.reads_used ?? 0} reads</span></div>
          {fused.matrix.length ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-mono text-2xs">
                <thead><tr><th className="th">Time</th>{fused.slots.map((slot) => <th key={slot.position} className="th text-center">{slot.position + 1}</th>)}</tr></thead>
                <tbody>
                  {fused.matrix.map((row) => (
                    <tr key={`${row.frame_idx}-${row.timestamp_sec}`}>
                      <td className="td whitespace-nowrap text-muted">{seconds(row.timestamp_sec)}</td>
                      {row.cells.map((cell, index) => (
                        <td key={index} title={`${(cell.confidence * 100).toFixed(1)}%`} className={`h-6 min-w-[22px] border border-white text-center font-semibold ${heat(cell.char, cell.confidence)}`}>{cell.char}</td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <th className="th">Fused</th>
                    {fused.slots.map((slot) => (
                      <td key={slot.position} title={slot.candidates.map((c) => `${c.char} ${(c.probability * 100).toFixed(0)}%`).join(", ") || "No runner-up"} className={`h-7 border border-white text-center text-xs font-semibold ${heat(slot.char, slot.confidence)}`}>{slot.char}</td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          ) : <Empty title="No plate reads">No character is inferred when a plate cannot be read.</Empty>}
          <div className="space-y-2 border-t border-line p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold">Investigator override</span>
              {rerank !== null && <span className="num text-2xs text-muted">Re-ranked in {rerank.toFixed(1)} ms</span>}
            </div>
            <div className="flex flex-wrap gap-px">
              {Array.from({ length: slotCount }, (_, position) => {
                const current = activeSlots[position];
                const locked = current?.locked;
                return (
                  <input
                    key={position}
                    aria-label={`Plate slot ${position + 1}`}
                    maxLength={1}
                    value={edits[position] ?? (current && current.char !== "?" ? current.char : "")}
                    placeholder="?"
                    onChange={(event) => setEdits({ ...edits, [position]: event.target.value.toUpperCase().replace(/[^A-Z0-9?]/g, "") })}
                    className={`h-8 w-7 border text-center font-mono text-xs font-semibold uppercase ${edits[position] !== undefined ? "border-navy bg-navy-tint" : locked ? "border-amber-400 bg-amber-50" : "border-line"}`}
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
          <div className="panel-head">Ranked shortlist</div>
          <Shortlist key={JSON.stringify(vehicle.overrides)} result={vehicle.match_result} />
        </section>
      </div>
    </div>
  );
}
