import { AlertTriangle, Play, Search, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, artifactUrl, progressUrl, type ClipUpload } from "../api/client";
import { Empty, LinkBadge, OUTCOMES, OUTCOME_ORDER, OutcomeBadge, Pagination, PlateText, pretty, score, seconds, shortHash, toLocalInput } from "../components/ui";
import type { CaseDetail, Clip, Outcome, PlateScript, ProgressEvent, VehicleSummary } from "../types";

const ACCEPT = ".mp4,.avi,.mov,.mkv,.zip";
const PAGE_SIZE = 20;
type Sort = "relevance" | "plate" | "first_seen" | "duration";

interface Props {
  detail: CaseDetail | null;
  vehicles: VehicleSummary[];
  onRefresh: () => Promise<void>;
  onOpenVehicle: (id: string) => void;
  onError: (message: string) => void;
}

function ClipRow({ clip, caseId, disabled, onSaved, onError }: {
  clip: Clip;
  caseId: string;
  disabled: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [time, setTime] = useState(toLocalInput(clip.recorded_at));
  useEffect(() => setTime(toLocalInput(clip.recorded_at)), [clip.recorded_at]);

  const save = async (body: { recorded_at?: string | null; plate_script?: PlateScript }) => {
    try {
      await api.updateClip(caseId, clip.id, body);
      await onSaved();
    } catch (error) {
      onError((error as Error).message);
    }
  };

  return (
    <tr>
      <td className="td font-medium">{clip.camera_label}{clip.location && <div className="text-2xs font-normal text-muted">{clip.location}</div>}</td>
      <td className="td max-w-[150px] truncate" title={clip.filename}>{clip.filename}</td>
      <td className="td num text-2xs" title={clip.sha256}>{shortHash(clip.sha256)}</td>
      <td className="td num whitespace-nowrap text-2xs">{clip.width}×{clip.height} · {clip.fps}fps · {clip.duration_sec}s</td>
      <td className="td">
        <input aria-label={`Capture time for ${clip.camera_label}`} type="datetime-local" disabled={disabled}
          className={`field w-[172px] ${clip.recorded_at ? "" : "border-amber-300 bg-amber-50"}`} value={time}
          onChange={(e) => setTime(e.target.value)}
          onBlur={() => { if (time !== toLocalInput(clip.recorded_at)) void save({ recorded_at: time ? new Date(time).toISOString() : null }); }} />
        {!clip.recorded_at && <div className="mt-0.5 text-2xs text-amber-800">Missing, time not validated</div>}
      </td>
      <td className="td">
        <select aria-label={`Plate script for ${clip.camera_label}`} disabled={disabled} className="field w-[150px]" value={clip.plate_script}
          onChange={(e) => void save({ plate_script: e.target.value as PlateScript })}>
          <option value="latin">Latin A–Z, 0–9</option>
          <option value="non_latin">Non-Latin, digits only</option>
        </select>
      </td>
    </tr>
  );
}

export default function CaseWorkspace({ detail, vehicles, onRefresh, onOpenVehicle, onError }: Props) {
  const [queue, setQueue] = useState<ClipUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "ALL">("ALL");
  const [camera, setCamera] = useState("");
  const [linkFilter, setLinkFilter] = useState("");
  const [sort, setSort] = useState<Sort>("relevance");
  const [page, setPage] = useState(1);
  const input = useRef<HTMLInputElement>(null);
  const caseId = detail?.id;
  const active = Boolean(detail?.running || detail?.status === "QUEUED" || detail?.status === "RUNNING");

  useEffect(() => {
    setProgress(null);
    setQueue([]);
    setQuery("");
    setOutcome("ALL");
    setCamera("");
    setLinkFilter("");
    setPage(1);
  }, [caseId]);

  useEffect(() => setPage(1), [query, outcome, camera, linkFilter, sort]);

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

  const counts = useMemo(() => {
    const result = Object.fromEntries(OUTCOME_ORDER.map((key) => [key, 0])) as Record<Outcome, number>;
    vehicles.forEach((vehicle) => { if (vehicle.outcome) result[vehicle.outcome] += 1; });
    return result;
  }, [vehicles]);

  const filtered = useMemo(() => {
    const needle = query.trim().toUpperCase();
    const list = vehicles.filter((vehicle) =>
      (outcome === "ALL" || vehicle.outcome === outcome)
      && (!camera || vehicle.camera_label === camera)
      && (!linkFilter || (linkFilter === "any" ? Boolean(vehicle.link_status) : vehicle.link_status === linkFilter))
      && (!needle || vehicle.plate.includes(needle) || (vehicle.top_plate ?? "").includes(needle)
        || `T${vehicle.track_id}` === needle || vehicle.camera_label.toUpperCase().includes(needle)));
    const rank = (vehicle: VehicleSummary) => OUTCOME_ORDER.indexOf(vehicle.outcome ?? "UNREADABLE_PLATE");
    return [...list].sort((a, b) => {
      if (sort === "plate") return b.known_chars - a.known_chars || a.plate.localeCompare(b.plate);
      if (sort === "first_seen") return a.first_seen_sec - b.first_seen_sec;
      if (sort === "duration") return b.frames_tracked - a.frames_tracked;
      return rank(a) - rank(b) || (b.top_score ?? 0) - (a.top_score ?? 0) || b.known_chars - a.known_chars
        || b.frames_tracked - a.frames_tracked;
    });
  }, [vehicles, query, outcome, camera, linkFilter, sort]);

  const pages = Math.max(Math.ceil(filtered.length / PAGE_SIZE), 1);
  const current = Math.min(page, pages);
  const visible = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const cameras = useMemo(() => [...new Set(vehicles.map((v) => v.camera_label))].sort(), [vehicles]);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const offset = (detail?.clips.length ?? 0) + queue.length;
    const added: ClipUpload[] = [...files].map((file, index) => ({
      file,
      camera_label: `Camera ${String.fromCharCode(65 + offset + index)}`,
      location: "",
      recorded_at: "",
      plate_script: "latin",
    }));
    setQueue((existing) => [...existing, ...added]);
  };

  const update = (index: number, patch: Partial<ClipUpload>) =>
    setQueue((items) => items.map((item, i) => (i === index ? { ...item, ...patch } : item)));

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

  const stats: { key: Outcome | "ALL"; label: string; value: number }[] = [
    { key: "ALL", label: "All tracks", value: vehicles.length },
    ...OUTCOME_ORDER.map((key) => ({ key, label: OUTCOMES[key].label, value: counts[key] })),
  ];

  return (
    <div className="space-y-3">
      {detail.stale && (
        <div role="status" className="flex flex-wrap items-center gap-2 border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle size={16} className="shrink-0" />
          <span className="min-w-0 flex-1">These tracks came from an older pipeline. Verdicts were re-scored, but re-run analysis to get the improved tracking and plate reading.</span>
          <button className="btn" disabled={active} onClick={analyze}>Re-run now</button>
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,4fr)_minmax(0,9fr)]">
        <section className="panel min-w-0">
          <div className="panel-head">Add evidence clips</div>
          <div className="space-y-2 p-3">
            <button
              onClick={() => input.current?.click()}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}
              className={`flex w-full flex-col items-center gap-1 border border-dashed px-3 py-4 text-xs ${dragging ? "border-navy bg-navy-tint" : "border-slate-300 hover:bg-canvas"}`}
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
                <div className="grid gap-1 sm:grid-cols-2">
                  <input aria-label="Camera label" className="field" placeholder="Camera label" value={item.camera_label} onChange={(e) => update(index, { camera_label: e.target.value })} />
                  <input aria-label="Location" className="field" placeholder="Location" value={item.location} onChange={(e) => update(index, { location: e.target.value })} />
                  <input aria-label="Recorded at" className="field" type="datetime-local" value={item.recorded_at} onChange={(e) => update(index, { recorded_at: e.target.value })} />
                  <select aria-label="Plate script" className="field" value={item.plate_script} onChange={(e) => update(index, { plate_script: e.target.value as PlateScript })}>
                    <option value="latin">Latin A–Z, 0–9</option>
                    <option value="non_latin">Non-Latin, digits only</option>
                  </select>
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
            <button className="btn btn-primary" disabled={!detail.clips.length || active} onClick={analyze}>
              <Play size={16} /> {detail.status === "COMPLETED" ? "Re-run analysis" : "Run analysis"}
            </button>
          </div>
          {(active || progress) && (
            <div className="border-b border-line px-3 py-2">
              <div className="mb-1 flex justify-between gap-2 text-2xs">
                <span className="truncate text-muted">{progress?.message ?? "Connecting to pipeline…"}</span>
                <span className="num">{(progress?.percent ?? 0).toFixed(0)}%</span>
              </div>
              <div className="h-1.5 bg-slate-100" role="progressbar" aria-label="Analysis progress" aria-valuenow={progress?.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
                <div className={`h-full transition-all ${progress?.status === "FAILED" ? "bg-rose-700" : "bg-navy"}`} style={{ width: `${progress?.percent ?? 0}%` }} />
              </div>
            </div>
          )}
          {detail.error && <div className="border-b border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{detail.error}</div>}
          {detail.clips.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse text-xs">
                <thead><tr><th className="th">Camera</th><th className="th">File</th><th className="th">SHA-256</th><th className="th">Video</th><th className="th">Capture time</th><th className="th">Plate script</th></tr></thead>
                <tbody>
                  {detail.clips.map((clip) => <ClipRow key={clip.id} clip={clip} caseId={detail.id} disabled={active} onSaved={onRefresh} onError={onError} />)}
                </tbody>
              </table>
            </div>
          ) : <Empty title="No evidence ingested">Each clip is hashed with SHA-256 on arrival.</Empty>}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <span>Results</span>
          {(detail.summary?.possible_links ?? 0) > 0 && <LinkCount count={detail.summary.possible_links} />}
        </div>
        {vehicles.length ? (
          <>
            <div className="grid grid-cols-2 gap-px border-b border-line bg-line sm:grid-cols-3 xl:grid-cols-6" role="group" aria-label="Filter by outcome">
              {stats.map((item) => (
                <button key={item.key} aria-pressed={outcome === item.key} onClick={() => setOutcome(item.key)}
                  className={`px-3 py-2 text-left ${outcome === item.key ? "bg-navy text-white" : "bg-white hover:bg-canvas"}`}>
                  <span className="num block text-base font-semibold">{item.value}</span>
                  <span className={`block text-2xs ${outcome === item.key ? "text-white/80" : "text-muted"}`}>{item.label}</span>
                </button>
              ))}
            </div>
            <div className="grid gap-2 border-b border-line p-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr]">
              <label className="relative"><Search size={16} className="absolute left-2 top-1.5 text-muted" /><input aria-label="Search results" className="field pl-7" placeholder="Search plate, camera or T12" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
              <select aria-label="Filter camera" className="field" value={camera} onChange={(e) => setCamera(e.target.value)}><option value="">All cameras</option>{cameras.map((v) => <option key={v} value={v}>{v}</option>)}</select>
              <select aria-label="Filter links" className="field" value={linkFilter} onChange={(e) => setLinkFilter(e.target.value)}>
                <option value="">Any link state</option><option value="any">Has a link</option><option value="proposed">Possible link</option><option value="confirmed">Confirmed link</option>
              </select>
              <select aria-label="Sort results" className="field" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="relevance">Sort: most relevant</option><option value="plate">Sort: most plate characters</option><option value="first_seen">Sort: first seen</option><option value="duration">Sort: longest tracked</option>
              </select>
            </div>
            {visible.length ? (
              <ul>
                {visible.map((vehicle) => (
                  <li key={vehicle.id} className="border-b border-line last:border-b-0">
                    <button onClick={() => onOpenVehicle(vehicle.id)}
                      className="grid w-full grid-cols-[72px_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-canvas lg:grid-cols-[72px_minmax(110px,1fr)_minmax(190px,1.3fr)_minmax(150px,1fr)_minmax(150px,1fr)]">
                      <span className="row-span-3 h-14 w-[72px] border border-line bg-slate-100 lg:row-span-1">
                        {vehicle.best_crop && <img loading="lazy" src={artifactUrl(vehicle.best_crop)} alt={`Vehicle track ${vehicle.track_id}`} className="h-full w-full object-cover" />}
                      </span>
                      <span className="min-w-0 text-xs">
                        <span className="block truncate font-medium">{vehicle.camera_label} · T{vehicle.track_id}</span>
                        <span className="num block text-2xs text-muted">{seconds(vehicle.first_seen_sec)}–{seconds(vehicle.last_seen_sec)}</span>
                      </span>
                      <span className="min-w-0"><PlateText text={vehicle.plate} size="sm" /></span>
                      <span className="flex min-w-0 flex-wrap items-center gap-1 lg:col-auto">
                        <OutcomeBadge outcome={vehicle.outcome} />
                        <LinkBadge status={vehicle.link_status} />
                        {vehicle.overridden && <span className="text-2xs text-amber-800">Verified</span>}
                      </span>
                      <span className="col-start-2 min-w-0 truncate text-2xs text-muted lg:col-start-auto">
                        {vehicle.top_plate ? <><span className="num font-semibold text-ink">{vehicle.top_plate}</span> · score <span className="num">{score(vehicle.top_score)}</span></>
                          : `${vehicle.attributes.colours[0]?.label ?? "colour unknown"} · ${pretty(vehicle.attributes.body_type.label)}`}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <Empty title="No tracks match these filters">Clear the search or choose another outcome.</Empty>}
            <div className="border-t border-line"><Pagination page={current} pages={pages} total={filtered.length} label="tracks" onChange={setPage} /></div>
          </>
        ) : <Empty title={detail.status === "COMPLETED" ? "No vehicles detected" : "No analysis yet"}>{detail.status === "COMPLETED" ? "The detector found no trackable vehicle in the usable frames." : "Run analysis to detect and track vehicles."}</Empty>}
      </section>
    </div>
  );
}

function LinkCount({ count }: { count: number }) {
  return <span className="text-2xs font-normal text-amber-800">{count} possible link{count === 1 ? "" : "s"} awaiting review</span>;
}
