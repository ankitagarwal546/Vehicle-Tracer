import { AlertTriangle, Play, Search, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, artifactUrl, progressUrl, reportHtmlUrl, reportPdfUrl, type ClipUpload } from "../api/client";
import { Badge, Empty, LinkBadge, OUTCOMES, OUTCOME_ORDER, OutcomeBadge, Pagination, PlateText, browserZone, pretty, score, seconds, shortHash, toZoneInput } from "../components/ui";
import { PLATE_FORMATS, type CaseDetail, type Clip, type Outcome, type PlateFormat, type ProgressEvent, type VehicleSummary } from "../types";

const ACCEPT = ".mp4,.avi,.mov,.mkv,.zip";
const PAGE_SIZE = 20;
type Sort = "relevance" | "plate" | "first_seen" | "duration";

interface Props {
  detail: CaseDetail | null;
  loading: boolean;
  vehicles: VehicleSummary[];
  onRefresh: () => Promise<void>;
  onOpenVehicle: (id: string) => void;
  onError: (message: string) => void;
}

const ZONES = ["UTC", "Asia/Kolkata", "Asia/Bangkok", "Europe/London", "Asia/Dubai", "America/New_York"];

function ClipRow({ clip, caseId, hasResults, disabled, onSaved, onError }: {
  clip: Clip;
  caseId: string;
  hasResults: boolean;
  disabled: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [zone, setZone] = useState(clip.timezone || browserZone());
  const [time, setTime] = useState(toZoneInput(clip.recorded_at, clip.timezone));
  useEffect(() => {
    setZone(clip.timezone || browserZone());
    setTime(toZoneInput(clip.recorded_at, clip.timezone));
  }, [clip.recorded_at, clip.timezone]);

  const save = async (body: { recorded_at?: string | null; timezone?: string | null; plate_format?: PlateFormat }) => {
    try {
      await api.updateClip(caseId, clip.id, body);
      await onSaved();
    } catch (error) {
      onError((error as Error).message);
    }
  };
  const saveTime = () => {
    if (time !== toZoneInput(clip.recorded_at, clip.timezone) || (time && zone !== clip.timezone)) {
      void save(time ? { timezone: zone, recorded_at: time } : { recorded_at: null, timezone: null });
    }
  };

  return (
    <li className="grid gap-x-3 gap-y-2 border-b border-line p-3 last:border-b-0 md:grid-cols-2 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1.6fr)_minmax(0,1fr)_auto]">
      <div className="min-w-0 text-xs">
        <div className="flex flex-wrap items-center gap-1.5 font-medium">{clip.camera_label}{clip.synthetic && <Badge tone="amber">Synthetic fixture</Badge>}</div>
        {clip.location && <div className="text-2xs text-muted">{clip.location}</div>}
        <div className="truncate text-2xs text-muted" title={clip.filename}>{clip.filename}</div>
        <div className="num text-2xs text-muted" title={clip.sha256}>SHA-256 {shortHash(clip.sha256)}</div>
        <div className="num text-2xs text-muted">{clip.width}×{clip.height} · {clip.fps}fps · {clip.duration_sec}s · {clip.codec}</div>
      </div>
      <div className="min-w-0">
        <span className="label">Capture time</span>
        <div className="grid gap-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <input aria-label={`Capture time for ${clip.camera_label}`} type="datetime-local" disabled={disabled}
            className={`field ${clip.recorded_at ? "" : "border-amber-300 bg-amber-50"}`} value={time}
            onChange={(e) => setTime(e.target.value)} onBlur={saveTime} />
          <input aria-label={`Timezone for ${clip.camera_label}`} list="timezones" disabled={disabled} className="field" value={zone}
            onChange={(e) => setZone(e.target.value)} onBlur={saveTime} />
        </div>
        {!clip.recorded_at && <div className="mt-0.5 text-2xs text-amber-800">Missing, temporal validation unavailable</div>}
      </div>
      <label className="block min-w-0">
        <span className="label">Plate format</span>
        <select aria-label={`Plate format for ${clip.camera_label}`} disabled={disabled} className="field" value={clip.plate_format}
          onChange={(e) => void save({ plate_format: e.target.value as PlateFormat })}>
          {PLATE_FORMATS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      {hasResults && (
        <div className="flex flex-wrap items-end gap-1">
          <a className="btn" href={reportHtmlUrl(caseId, clip.id)} target="_blank" rel="noreferrer">Clip HTML</a>
          <a className="btn" href={reportPdfUrl(caseId, false, clip.id)}>Clip PDF</a>
        </div>
      )}
    </li>
  );
}

export default function CaseWorkspace({ detail, loading, vehicles, onRefresh, onOpenVehicle, onError }: Props) {
  const [queue, setQueue] = useState<ClipUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "ALL">("ALL");
  const [camera, setCamera] = useState("");
  const [linkFilter, setLinkFilter] = useState("");
  const [readability, setReadability] = useState("");
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
    setReadability("");
    setPage(1);
  }, [caseId]);

  useEffect(() => setPage(1), [query, outcome, camera, linkFilter, readability, sort]);

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
      && (!readability || vehicle.readability === readability)
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
  }, [vehicles, query, outcome, camera, linkFilter, readability, sort]);

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
      timezone: browserZone(),
      latitude: "",
      longitude: "",
      plate_format: "latin_any",
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
    return (
      <div className="panel">
        {loading ? <div role="status" className="px-4 py-8 text-center text-xs text-muted">Loading case…</div>
          : <Empty title="No case selected">Create a case from the header to begin ingesting CCTV evidence.</Empty>}
      </div>
    );
  }

  const stats: { key: Outcome | "ALL"; label: string; value: number }[] = [
    { key: "ALL", label: "All tracks", value: vehicles.length },
    ...OUTCOME_ORDER.map((key) => ({ key, label: OUTCOMES[key].label, value: counts[key] })),
  ];

  return (
    <div className="space-y-3">
      <datalist id="timezones">{ZONES.map((zone) => <option key={zone} value={zone} />)}</datalist>
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
                  <input aria-label="Timezone" list="timezones" className="field" value={item.timezone} onChange={(e) => update(index, { timezone: e.target.value })} />
                  <select aria-label="Plate format" className="field" value={item.plate_format} onChange={(e) => update(index, { plate_format: e.target.value as PlateFormat })}>
                    {PLATE_FORMATS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <span className="grid grid-cols-2 gap-1">
                    <input aria-label="Latitude" inputMode="decimal" className="field" placeholder="Latitude" value={item.latitude} onChange={(e) => update(index, { latitude: e.target.value })} />
                    <input aria-label="Longitude" inputMode="decimal" className="field" placeholder="Longitude" value={item.longitude} onChange={(e) => update(index, { longitude: e.target.value })} />
                  </span>
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
            <>
              <ul className="xl:max-h-[300px] xl:overflow-y-auto">
                {detail.clips.map((clip) => <ClipRow key={clip.id} clip={clip} caseId={detail.id} hasResults={detail.status === "COMPLETED"} disabled={active} onSaved={onRefresh} onError={onError} />)}
              </ul>
              <p className="border-t border-line px-3 py-1.5 text-2xs text-muted">Changing a plate format applies on the next analysis run.</p>
            </>
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
            <div className="grid gap-2 border-b border-line p-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr_1fr]">
              <label className="relative"><Search size={16} className="absolute left-2 top-1.5 text-muted" /><input aria-label="Search results" className="field pl-7" placeholder="Search plate, camera or T12" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
              <select aria-label="Filter camera" className="field" value={camera} onChange={(e) => setCamera(e.target.value)}><option value="">All cameras</option>{cameras.map((v) => <option key={v} value={v}>{v}</option>)}</select>
              <select aria-label="Filter plate readability" className="field" value={readability} onChange={(e) => setReadability(e.target.value)}>
                <option value="">Any readability</option><option value="comparable">5+ characters</option><option value="partial">1–4 characters</option><option value="none">No characters</option>
              </select>
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
