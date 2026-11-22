import { Play, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, artifactUrl, progressUrl, type ClipUpload } from "../api/client";
import { Badge, Empty, PlateText, VerdictBadge, percent, pretty, seconds, shortHash } from "../components/ui";
import type { CaseDetail, ProgressEvent, VehicleSummary } from "../types";

const ACCEPT = ".mp4,.avi,.mov,.mkv,.zip";

interface Props {
  detail: CaseDetail | null;
  vehicles: VehicleSummary[];
  onRefresh: () => Promise<void>;
  onOpenVehicle: (id: string) => void;
  onError: (message: string) => void;
}

export default function CaseWorkspace({ detail, vehicles, onRefresh, onOpenVehicle, onError }: Props) {
  const [queue, setQueue] = useState<ClipUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const caseId = detail?.id;
  const active = detail?.running || detail?.status === "QUEUED" || detail?.status === "RUNNING";

  useEffect(() => {
    setProgress(null);
    setQueue([]);
  }, [caseId]);

  useEffect(() => {
    if (!caseId || !active) return;
    const source = new EventSource(progressUrl(caseId));
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as ProgressEvent;
      setProgress(event);
      if (event.status === "COMPLETED" || event.status === "FAILED") {
        source.close();
        void onRefresh();
      }
    };
    source.onerror = () => {
      source.close();
      void onRefresh();
    };
    return () => source.close();
  }, [caseId, active, onRefresh]);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const offset = (detail?.clips.length ?? 0) + queue.length;
    const added = [...files].map((file, index) => ({
      file,
      camera_label: `Camera ${String.fromCharCode(65 + offset + index)}`,
      location: "",
      recorded_at: "",
    }));
    setQueue((current) => [...current, ...added]);
  };

  const update = (index: number, patch: Partial<ClipUpload>) =>
    setQueue((current) => current.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const upload = async () => {
    if (!caseId) return;
    setUploading(true);
    try {
      await api.uploadClips(caseId, queue);
      setQueue([]);
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const analyze = async () => {
    if (!caseId) return;
    try {
      setProgress({ stage: "queued", percent: 0, message: "Queued for analysis", status: "RUNNING" });
      await api.analyze(caseId);
      await onRefresh();
    } catch (error) {
      setProgress(null);
      onError((error as Error).message);
    }
  };

  if (!detail) {
    return <div className="panel"><Empty title="No case selected">Create a case from the header to begin ingesting CCTV evidence.</Empty></div>;
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section className="panel">
          <div className="panel-head">Add evidence clips</div>
          <div className="space-y-2 p-3">
            <button
              onClick={() => input.current?.click()}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}
              className={`flex w-full flex-col items-center gap-1 border border-dashed px-3 py-5 text-xs ${dragging ? "border-navy bg-navy-tint" : "border-slate-300 hover:bg-canvas"}`}
            >
              <Upload size={16} className="text-muted" />
              <span className="font-medium">Drop CCTV clips or choose files</span>
              <span className="text-2xs text-muted">MP4, AVI, MOV, MKV, or ZIP of frames</span>
            </button>
            <input ref={input} type="file" accept={ACCEPT} multiple className="hidden" onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }} />
            {queue.map((item, index) => (
              <div key={`${item.file.name}-${index}`} className="space-y-1 border border-line p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium">{item.file.name}</span>
                  <button aria-label={`Remove ${item.file.name}`} className="text-muted hover:text-ink" onClick={() => setQueue(queue.filter((_, i) => i !== index))}><X size={16} /></button>
                </div>
                <div className="grid gap-1 sm:grid-cols-3">
                  <input aria-label="Camera label" className="field" placeholder="Camera label" value={item.camera_label} onChange={(e) => update(index, { camera_label: e.target.value })} />
                  <input aria-label="Location" className="field" placeholder="Location" value={item.location} onChange={(e) => update(index, { location: e.target.value })} />
                  <input aria-label="Recorded at" className="field" type="datetime-local" value={item.recorded_at} onChange={(e) => update(index, { recorded_at: e.target.value })} />
                </div>
              </div>
            ))}
            {queue.length > 0 && (
              <button className="btn btn-primary w-full" disabled={uploading} onClick={upload}>
                {uploading ? "Hashing and ingesting…" : `Ingest ${queue.length} clip${queue.length > 1 ? "s" : ""}`}
              </button>
            )}
          </div>
        </section>

        <section className="panel min-w-0">
          <div className="panel-head">
            <span>Chain of custody <span className="font-normal text-muted">· {detail.clips.length} clip(s)</span></span>
            <button className="btn btn-primary" disabled={!detail.clips.length || Boolean(active)} onClick={analyze}>
              <Play size={16} /> {detail.status === "COMPLETED" ? "Re-run analysis" : "Run analysis"}
            </button>
          </div>
          {(active || progress) && (
            <div className="border-b border-line px-3 py-2">
              <div className="mb-1 flex justify-between gap-2 text-2xs">
                <span className="truncate text-muted">{progress?.message ?? "Connecting to pipeline…"}</span>
                <span className="num">{(progress?.percent ?? 0).toFixed(0)}%</span>
              </div>
              <div className="h-1.5 bg-slate-100" role="progressbar" aria-valuenow={progress?.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
                <div className={`h-full transition-all ${progress?.status === "FAILED" ? "bg-rose-700" : "bg-navy"}`} style={{ width: `${progress?.percent ?? 0}%` }} />
              </div>
            </div>
          )}
          {detail.error && <div className="border-b border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{detail.error}</div>}
          {detail.clips.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] border-collapse text-xs">
                <thead><tr><th className="th">Camera</th><th className="th">File</th><th className="th">SHA-256</th><th className="th">Video</th><th className="th">Recorded</th></tr></thead>
                <tbody>
                  {detail.clips.map((clip) => (
                    <tr key={clip.id}>
                      <td className="td font-medium">{clip.camera_label}{clip.location && <div className="text-2xs font-normal text-muted">{clip.location}</div>}</td>
                      <td className="td max-w-[150px] truncate" title={clip.filename}>{clip.filename}</td>
                      <td className="td num text-2xs" title={clip.sha256}>{shortHash(clip.sha256)}</td>
                      <td className="td num whitespace-nowrap text-2xs">{clip.width}×{clip.height} · {clip.fps}fps · {clip.duration_sec}s</td>
                      <td className="td num whitespace-nowrap text-2xs">{clip.recorded_at ? new Date(clip.recorded_at).toLocaleString() : "Not supplied"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty title="No evidence ingested">Each clip is hashed with SHA-256 on arrival.</Empty>}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">Detected vehicles <span className="num font-normal text-muted">{vehicles.length}</span></div>
        {vehicles.length ? (
          <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-4">
            {vehicles.map((vehicle) => (
              <button key={vehicle.id} onClick={() => onOpenVehicle(vehicle.id)} className="flex gap-2 bg-white p-2 text-left hover:bg-canvas">
                <span className="h-20 w-24 shrink-0 border border-line bg-slate-100">
                  {vehicle.best_crop && <img src={artifactUrl(vehicle.best_crop)} alt={`Vehicle track ${vehicle.track_id}`} className="h-full w-full object-cover" />}
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="flex items-center justify-between gap-1 text-2xs text-muted">
                    <span className="truncate">{vehicle.camera_label} · T{vehicle.track_id}</span>
                    {vehicle.entity_id && <Badge tone="navy">Linked</Badge>}
                  </span>
                  <span className="block"><PlateText text={vehicle.plate} size="sm" /></span>
                  <span className="block truncate text-2xs text-muted">
                    {vehicle.attributes.colours[0]?.label} · {pretty(vehicle.attributes.body_type.label)} · <span className="num">{seconds(vehicle.first_seen_sec)}</span>
                  </span>
                  <span className="flex items-center gap-1.5"><VerdictBadge status={vehicle.status} /><span className="num text-2xs">{vehicle.status === "CONFIDENT_SHORTLIST" ? percent(vehicle.top_confidence) : ""}</span></span>
                </span>
              </button>
            ))}
          </div>
        ) : <Empty title={detail.status === "COMPLETED" ? "No vehicles detected" : "No analysis yet"}>{detail.status === "COMPLETED" ? "The detector found no trackable vehicle in the usable frames." : "Run analysis to detect and track vehicles."}</Empty>}
      </section>
    </div>
  );
}
