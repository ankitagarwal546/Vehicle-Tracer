import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FileText, Play, Plus, RefreshCw, RotateCcw, ScanSearch, Search, Share2, Square, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, artifactUrl, progressUrl, reportHtmlUrl, reportPdfUrl, type ClipUpload } from "../api/client";
import { Badge, Empty, LinkBadge, Notice, OUTCOMES, OUTCOME_ORDER, OutcomeBadge, PageHeader, Pagination, PlateText, browserZone, clock, pretty, score, seconds, toZoneInput } from "../components/ui";
import { actionLabel, analysisState, reviewState } from "../lib/overview";
import { PLATE_FORMATS, type CaseDetail, type Clip, type CoverageRow, type Outcome, type PlateFormat, type ProgressEvent, type VehicleSummary } from "../types";

const ACCEPT = ".mp4,.avi,.mov,.mkv,.zip";
const PAGE_SIZE = 20;
const LIVE_REFRESH_MS = 3000;
const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
const ZONES = ["UTC", "Asia/Kolkata", "Asia/Bangkok", "Europe/London", "Asia/Dubai", "America/New_York"];
type Sort = "relevance" | "plate" | "first_seen" | "duration";

interface Props {
  detail: CaseDetail | null;
  loading: boolean;
  vehicles: VehicleSummary[];
  onRefresh: () => Promise<void>;
  onOpenVehicle: (id: string) => void;
  onOpenRegistry: () => void;
  onOpenTrace: () => void;
  onOpenReports: () => void;
  onNewCase: () => void;
  onError: (message: string) => void;
}

function coverageState(vehicle: VehicleSummary) {
  const coverage = vehicle.registry_coverage;
  if (!coverage) return "";
  if (coverage.compatible_records === 0) return "no_coverage";
  return coverage.searched ? "searched" : "incomplete";
}

function SectionHead({ step, title, note, actions }: { step: number; title: string; note?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
      <div className="min-w-0">
        <h2 className="section-title"><span className="num mr-1.5 text-accent-soft">{step}</span>{title}</h2>
        {note && <p className="text-2xs text-muted">{note}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-1.5">{actions}</div>}
    </div>
  );
}

function StageRail({ detail, active }: { detail: CaseDetail; active: boolean }) {
  const summary = detail.summary;
  const hasResults = Boolean(detail.has_completed_run);
  const recovered = (summary?.readable_plates ?? 0) + (summary?.partial_plates ?? 0);
  const compared = (summary?.plate_candidates ?? 0) + (summary?.ambiguous ?? 0) + (summary?.no_registry_match ?? 0);
  const open = (summary?.possible_links ?? 0) + (summary?.tracks_review ?? 0);
  const steps = [
    { id: "ingest", name: "Ingest", value: `${detail.clips.length} clip${detail.clips.length === 1 ? "" : "s"}`, done: detail.clips.length > 0, warn: (summary?.clips_missing_time ?? 0) > 0 },
    { id: "detect", name: "Detect", value: `${summary?.tracks ?? 0} tracks`, done: hasResults, warn: false },
    { id: "recover", name: "Recover", value: `${recovered} with characters`, done: hasResults, warn: false },
    { id: "recover", name: "Match", value: summary?.no_registry_coverage ? `${summary.no_registry_coverage} not searched` : `${compared} compared`, done: hasResults, warn: Boolean(summary?.no_registry_coverage) },
    { id: "review", name: "Review", value: `${open} open`, done: hasResults, warn: open > 0 },
  ];
  return (
    <nav aria-label="Case stages" className="panel overflow-x-auto">
      <ol className="flex min-w-[620px]">
        {steps.map((step, index) => (
          <li key={step.name} className="min-w-0 flex-1 border-r border-line last:border-r-0">
            <button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-canvas" onClick={() => document.getElementById(step.id)?.scrollIntoView({ block: "start" })}>
              <span className={`num flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-2xs font-semibold ${step.done ? "border-accent bg-accent text-white" : active ? "border-accent text-accent-soft" : "border-slate-400 text-muted"}`}>{index + 1}</span>
              <span className="min-w-0">
                <span className="block text-xs font-semibold">{step.name}</span>
                <span className={`num block truncate text-2xs ${step.warn ? "text-amber-900" : "text-muted"}`}>{step.value}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function ClipCard({ clip, caseId, coverage, hasResults, disabled, onSaved, onError }: {
  clip: Clip;
  caseId: string;
  coverage?: CoverageRow;
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
  const process = clip.processing;

  return (
    <li className="flex min-w-0 flex-col rounded-evidence border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-1.5 border-b border-line px-2.5 py-2">
        <div className="min-w-0">
          <div className="text-xs font-semibold">{clip.camera_label}</div>
          {clip.location && <div className="text-2xs text-muted">{clip.location}</div>}
          <div className="break-all text-2xs text-muted">{clip.filename}</div>
        </div>
        {clip.synthetic && <Badge tone="amber">Demo evidence</Badge>}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 px-2.5 py-2 text-2xs sm:grid-cols-4">
        <div><dt className="text-muted">Resolution</dt><dd className="num">{clip.width}×{clip.height}</dd></div>
        <div><dt className="text-muted">Frame rate</dt><dd className="num">{clip.fps} fps</dd></div>
        <div><dt className="text-muted">Duration</dt><dd className="num">{clip.duration_sec} s</dd></div>
        <div><dt className="text-muted">Codec</dt><dd className="num">{clip.codec}</dd></div>
        <div className="col-span-full"><dt className="text-muted">SHA-256</dt><dd className="num break-all">{clip.sha256}</dd></div>
        {process?.raw_tracks != null && (
          <div className="col-span-full"><dt className="text-muted">Tracking</dt><dd className="num">{process.raw_tracks} raw · {process.fragments_merged ?? 0} merged · {process.dropped_short_or_clipped ?? 0} too short or clipped · {process.tracks ?? 0} kept</dd></div>
        )}
      </dl>
      <div className="mt-auto space-y-2 border-t border-line px-2.5 py-2">
        <div>
          <span className="label">Capture time and timezone</span>
          <div className="grid gap-1 sm:grid-cols-2">
            <input aria-label={`Capture time for ${clip.camera_label}`} type="datetime-local" disabled={disabled}
              className={`field ${clip.recorded_at ? "" : "border-amber-400 bg-amber-50"}`} value={time}
              onChange={(e) => setTime(e.target.value)} onBlur={saveTime} />
            <input aria-label={`Timezone for ${clip.camera_label}`} list="timezones" disabled={disabled} className="field" value={zone}
              onChange={(e) => setZone(e.target.value)} onBlur={saveTime} />
          </div>
          {!clip.recorded_at && <div className="mt-1 flex items-start gap-1 text-2xs text-amber-900"><Clock3 size={12} aria-hidden="true" className="mt-0.5 shrink-0" /> Capture time missing, so temporal checks cannot be validated. The timezone is only a default for a time you enter.</div>}
        </div>
        <label className="block">
          <span className="label">Plate format</span>
          <select id={`format-${clip.id}`} aria-label={`Plate format for ${clip.camera_label}`} disabled={disabled} className="field" value={clip.plate_format}
            onChange={(e) => void save({ plate_format: e.target.value as PlateFormat })}>
            {PLATE_FORMATS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          {coverage && (
            <span className={`mt-1 flex items-center gap-1 text-2xs ${coverage.status === "no_coverage" ? "font-medium text-amber-900" : "text-muted"}`}>
              {coverage.status === "no_coverage" && <AlertTriangle size={12} aria-hidden="true" />}
              <span className="num">{coverage.compatible_records.toLocaleString()}</span> of <span className="num">{coverage.total_records.toLocaleString()}</span> registry records compatible
            </span>
          )}
        </label>
        {hasResults && (
          <div className="flex flex-wrap gap-1">
            <a className="btn" href={reportHtmlUrl(caseId, clip.id)} target="_blank" rel="noreferrer">Clip HTML</a>
            <a className="btn" href={reportPdfUrl(caseId, false, clip.id)}>Clip PDF</a>
          </div>
        )}
      </div>
    </li>
  );
}

export default function CaseWorkspace({ detail, loading, vehicles, onRefresh, onOpenVehicle, onOpenRegistry, onOpenTrace, onOpenReports, onNewCase, onError }: Props) {
  const [queue, setQueue] = useState<ClipUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<Outcome | "ALL">("ALL");
  const [camera, setCamera] = useState("");
  const [linkFilter, setLinkFilter] = useState("");
  const [readability, setReadability] = useState("");
  const [coverageFilter, setCoverageFilter] = useState("");
  const [qualityFilter, setQualityFilter] = useState("");
  const [sort, setSort] = useState<Sort>("relevance");
  const [page, setPage] = useState(1);
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [rematching, setRematching] = useState(false);
  const [notice, setNotice] = useState("");
  const lastLive = useRef({ at: 0, tracks: 0 });
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
    setCoverageFilter("");
    setQualityFilter("");
    setConfirming(false);
    setCancelling(false);
    setNotice("");
    setPage(1);
  }, [caseId]);

  useEffect(() => setPage(1), [query, outcome, camera, linkFilter, readability, coverageFilter, qualityFilter, sort]);

  useEffect(() => {
    if (!caseId || !active) return;
    const source = new EventSource(progressUrl(caseId));
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as ProgressEvent;
      setProgress(event);
      if (TERMINAL.has(event.status)) {
        source.close();
        setCancelling(false);
        void onRefresh();
        return;
      }
      const done = event.tracks_done ?? 0;
      if (done > lastLive.current.tracks && Date.now() - lastLive.current.at > LIVE_REFRESH_MS) {
        lastLive.current = { at: Date.now(), tracks: done };
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
      && (!coverageFilter || coverageState(vehicle) === coverageFilter)
      && (!qualityFilter || vehicle.track_quality?.tier === qualityFilter)
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
  }, [vehicles, query, outcome, camera, linkFilter, readability, coverageFilter, qualityFilter, sort]);

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

  const analyze = async (acknowledge = false) => {
    if (!caseId) return;
    if (detail?.preflight?.requires_acknowledgement && !acknowledge) {
      setConfirming(true);
      return;
    }
    try {
      setConfirming(false);
      setNotice("");
      lastLive.current = { at: 0, tracks: 0 };
      setProgress({ stage: "queued", stage_label: "Queued", percent: 0, message: "Queued for analysis", status: "RUNNING" });
      await api.analyze(caseId, acknowledge);
      await onRefresh();
    } catch (error) {
      setProgress(null);
      onError((error as Error).message);
      await onRefresh();
    }
  };

  const cancel = async () => {
    if (!caseId) return;
    setCancelling(true);
    try {
      await api.cancel(caseId);
    } catch (error) {
      setCancelling(false);
      onError((error as Error).message);
    }
  };

  const rematch = async () => {
    if (!caseId) return;
    setRematching(true);
    try {
      const result = await api.rescore(caseId);
      setNotice(`Re-matched ${result.tracks} tracks against the current registry. OCR evidence was not changed.`);
      await onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setRematching(false);
    }
  };

  const changeFormat = (clipId?: string) => {
    const target = clipId ?? detail?.preflight?.coverage.find((row) => row.status === "no_coverage")?.clip_id;
    const field = target ? document.getElementById(`format-${target}`) : null;
    field?.scrollIntoView({ block: "center" });
    field?.focus();
  };

  if (!detail) {
    return (
      <div className="panel">
        {loading ? <div role="status" className="px-4 py-8 text-center text-xs text-muted">Loading investigation…</div>
          : <Empty title="No investigation selected">Create an investigation to begin ingesting CCTV evidence.<div><button className="btn btn-primary mt-2" onClick={onNewCase}><Plus size={15} /> New investigation</button></div></Empty>}
      </div>
    );
  }

  const stats: { key: Outcome | "ALL"; label: string; value: number }[] = [
    { key: "ALL", label: "All tracks", value: vehicles.length },
    ...OUTCOME_ORDER.map((key) => ({ key, label: OUTCOMES[key].short, value: counts[key] })),
  ];
  const summary = detail.summary;
  const preflight = detail.preflight;
  const hasResults = Boolean(detail.has_completed_run);
  const gaps = preflight?.coverage.filter((row) => row.status === "no_coverage") ?? [];
  const showPreflight = !active && Boolean(preflight?.warnings.length) && (!hasResults || confirming);
  const showProgress = active || progress?.status === "COMPLETED";
  const uncovered = summary?.coverage?.filter((row) => row.status === "no_coverage") ?? [];
  const needsRematch = hasResults && !active && Boolean(summary?.registry_changed || summary?.format_changed);
  const state = analysisState(detail);
  const review = reviewState(detail);
  const nextFlagged = vehicles.find((vehicle) => vehicle.track_quality?.tier === "review");
  const coverageFor = (clipId: string) => (preflight?.coverage ?? summary?.coverage)?.find((row) => row.clip_id === clipId);

  return (
    <div className="space-y-3">
      <datalist id="timezones">{ZONES.map((zone) => <option key={zone} value={zone} />)}</datalist>
      <PageHeader
        eyebrow="Case workspace"
        title={detail.title}
        description={<span className="inline-flex flex-wrap items-center gap-1.5"><Badge tone={state.tone}>{state.label}</Badge><Badge tone={review.tone}>{review.label}</Badge>{detail.clips.some((clip) => clip.synthetic) && <Badge tone="amber" title="Clips in this case are synthetic test fixtures">Demo evidence</Badge>}{detail.pipeline_version && <span className="num text-2xs">pipeline v{detail.pipeline_version}</span>}</span>}
        actions={<>
          {hasResults && <button className="btn" onClick={onOpenReports}><FileText size={15} /> Reports</button>}
          {active
            ? <button className="btn" disabled={cancelling} onClick={() => void cancel()}><Square size={14} /> {cancelling ? "Cancelling…" : "Cancel analysis"}</button>
            : <button className="btn btn-primary" disabled={!detail.clips.length} onClick={() => void analyze()}><Play size={15} /> {hasResults ? "Re-run analysis" : "Run analysis"}</button>}
        </>}
      />
      <StageRail detail={detail} active={active} />

      {detail.stale && (
        <Notice icon={<AlertTriangle size={15} />} action={<button className="btn" disabled={active} onClick={() => void analyze()}>Re-run now</button>}>
          These tracks came from an older pipeline. Verdicts were re-scored, but re-run analysis to get the improved tracking and plate reading.
        </Notice>
      )}
      {showProgress && (
        <div className="panel px-3 py-2">
          <div className="mb-1 flex flex-wrap justify-between gap-x-3 text-2xs">
            <span className="min-w-0"><span className="font-semibold">{progress?.stage_label ?? "Connecting"}</span> <span className="text-muted">{progress?.message ?? "Connecting to pipeline…"}</span></span>
            <span className="num text-muted">
              {progress?.elapsed_sec != null && `${clock(progress.elapsed_sec)} elapsed`}
              {progress?.eta_sec != null && ` · about ${clock(progress.eta_sec)} left`}
              <span className="ml-2 font-semibold text-ink">{(progress?.percent ?? 0).toFixed(0)}%</span>
            </span>
          </div>
          <div className="h-1.5 bg-slate-100" role="progressbar" aria-label="Analysis progress" aria-valuenow={progress?.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-accent transition-all" style={{ width: `${progress?.percent ?? 0}%` }} />
          </div>
        </div>
      )}
      {!active && (detail.status === "FAILED" || detail.status === "CANCELLED") && (
        <Notice tone={detail.status === "FAILED" ? "crimson" : "amber"} live="alert" action={<button className="btn" onClick={() => void analyze()}><RotateCcw size={14} /> Retry</button>}>
          {detail.status === "FAILED" ? `Analysis failed. ${detail.error ?? ""}` : "Analysis was cancelled."} Partial tracks were discarded. {hasResults ? "The previous completed results are still shown." : "No results were saved."} Evidence files were not changed.
        </Notice>
      )}
      {showPreflight && preflight && (
        <Notice tone={gaps.length ? "amber" : "slate"} live={gaps.length ? "alert" : "status"} icon={gaps.length ? <AlertTriangle size={15} /> : undefined}
          title={gaps.length ? "Registry coverage check: no compatible records" : "Before you run"}>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {preflight.warnings.map((warning) => <li key={`${warning.code}-${warning.clip_id}`}>{warning.message}</li>)}
          </ul>
          {gaps.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button className="btn btn-primary" onClick={onOpenRegistry}><Upload size={14} /> Upload compatible registry</button>
              <button className="btn" onClick={() => changeFormat()}>Change plate format</button>
              <button className="btn" onClick={() => void analyze(true)}>{gaps.length === preflight.coverage.length ? "Run OCR only" : "Run with coverage gap"}</button>
            </div>
          )}
        </Notice>
      )}
      {!active && uncovered.length > 0 && vehicles.length > 0 && (
        <Notice live="alert" icon={<AlertTriangle size={15} />} title="No registry coverage" action={<button className="btn" onClick={onOpenRegistry}>Upload compatible registry</button>}>
          {uncovered.map((row) => `${row.camera_label} (${row.format_label}): ${row.compatible_records} of ${row.total_records.toLocaleString()} records compatible`).join("; ")}.{" "}
          {summary.no_registry_coverage} readable plate{summary.no_registry_coverage === 1 ? " was" : "s were"} kept as OCR evidence but not searched. {summary.no_registry_coverage === 1 ? "This is" : "These are"} not no-match results.
        </Notice>
      )}
      {!active && (summary?.format_hints ?? []).map((hint) => (
        <Notice key={`${hint.clip_id}-${hint.family}`} live="alert" icon={<AlertTriangle size={15} />} title="Possible format gap" action={<button className="btn" onClick={() => changeFormat(hint.clip_id)}>Change plate format</button>}>
          {hint.message}
        </Notice>
      ))}
      {needsRematch && (
        <Notice action={<button className="btn btn-primary" disabled={rematching} onClick={() => void rematch()}><RefreshCw size={14} /> {rematching ? "Re-matching…" : "Re-match stored evidence"}</button>}>
          {summary.format_changed ? "A camera's plate format changed" : "The registry changed"} since these results were scored.
        </Notice>
      )}
      {notice && <div role="status" className="flex items-center gap-1.5 rounded-evidence border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-900"><CheckCircle2 size={15} aria-hidden="true" />{notice}</div>}

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_330px]">
        <div className="min-w-0 space-y-3">
          <section id="ingest" className="panel scroll-mt-3">
            <SectionHead step={1} title="Ingest" note="Chain of custody for each clip. Evidence is hashed on arrival and stored read-only."
              actions={<button className="btn" onClick={() => input.current?.click()}><Upload size={14} /> Add clips</button>} />
            <div className="space-y-2 p-2">
              <input ref={input} type="file" accept={ACCEPT} multiple className="hidden" onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }} />
              {detail.clips.length > 0 && (
                <ul tabIndex={detail.clips.length > 2 ? 0 : undefined} aria-label="Evidence clips" className={`grid gap-2 lg:grid-cols-2 2xl:grid-cols-3 ${detail.clips.length > 2 ? "lg:max-h-[520px] lg:overflow-y-auto lg:pr-1" : ""}`}>
                  {detail.clips.map((clip) => <ClipCard key={clip.id} clip={clip} caseId={detail.id} coverage={coverageFor(clip.id)} hasResults={hasResults} disabled={active} onSaved={onRefresh} onError={onError} />)}
                </ul>
              )}
              <button
                type="button"
                onClick={() => input.current?.click()}
                onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}
                className={`flex w-full flex-wrap items-center justify-center gap-x-2 gap-y-0.5 rounded-evidence border border-dashed px-3 ${detail.clips.length ? "py-2" : "py-6"} text-xs ${dragging ? "border-accent bg-accent-tint" : "border-slate-400 hover:bg-canvas"}`}
              >
                <Upload size={15} aria-hidden="true" className="text-muted" />
                <span className="font-medium">Drop CCTV clips or choose files</span>
                <span className="text-2xs text-muted">MP4, AVI, MOV, MKV, or ZIP of frames</span>
              </button>
              {queue.map((item, index) => (
                <div key={`${item.file.name}-${index}`} className="space-y-1 rounded-evidence border border-line p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium">{item.file.name}</span>
                    <button aria-label={`Remove ${item.file.name}`} className="p-1 text-muted hover:text-ink" onClick={() => setQueue(queue.filter((_, i) => i !== index))}><X size={16} /></button>
                  </div>
                  <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-4">
                    <input aria-label="Camera label" className="field" placeholder="Camera label" value={item.camera_label} onChange={(e) => update(index, { camera_label: e.target.value })} />
                    <input aria-label="Location" className="field" placeholder="Location" value={item.location} onChange={(e) => update(index, { location: e.target.value })} />
                    <input aria-label="Recorded at" className="field" type="datetime-local" value={item.recorded_at} onChange={(e) => update(index, { recorded_at: e.target.value })} />
                    <input aria-label="Timezone" list="timezones" className="field" value={item.timezone} onChange={(e) => update(index, { timezone: e.target.value })} />
                    <select aria-label="Plate format" className="field" value={item.plate_format} onChange={(e) => update(index, { plate_format: e.target.value as PlateFormat })}>
                      {PLATE_FORMATS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <input aria-label="Latitude" inputMode="decimal" className="field" placeholder="Latitude" value={item.latitude} onChange={(e) => update(index, { latitude: e.target.value })} />
                    <input aria-label="Longitude" inputMode="decimal" className="field" placeholder="Longitude" value={item.longitude} onChange={(e) => update(index, { longitude: e.target.value })} />
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

          <section id="detect" className="panel scroll-mt-3">
            <SectionHead step={2} title="Detect" note={active && vehicles.length ? `Showing tracks as they finish. Counts are provisional.${hasResults ? " Reports still use the previous completed run." : ""}` : "Tracked vehicles with first and last sighting, evidence quality and outcome."}
              actions={(summary?.possible_links ?? 0) > 0 ? <span className="text-2xs font-medium text-amber-900">{summary.possible_links} possible link{summary.possible_links === 1 ? "" : "s"} to review</span> : undefined} />
            {vehicles.length ? (
              <>
                <div className="grid grid-cols-2 gap-px border-b border-line bg-line sm:grid-cols-4 xl:grid-cols-7" role="group" aria-label="Filter by outcome">
                  {stats.map((item) => (
                    <button key={item.key} aria-pressed={outcome === item.key} onClick={() => setOutcome(item.key)} title={item.key === "ALL" ? undefined : OUTCOMES[item.key].help}
                      className={`px-3 py-1.5 text-left ${outcome === item.key ? "bg-accent text-white" : "bg-surface hover:bg-canvas"}`}>
                      <span className="num block text-base font-semibold">{item.value}</span>
                      <span className={`block text-2xs ${outcome === item.key ? "text-white" : "text-muted"}`}>{item.label}</span>
                    </button>
                  ))}
                </div>
                <div className="grid gap-1.5 border-b border-line p-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-[minmax(0,2fr)_repeat(6,minmax(0,1fr))]">
                  <label className="relative"><Search size={15} aria-hidden="true" className="absolute left-2 top-2 text-muted" /><input aria-label="Search results" className="field pl-7" placeholder="Search plate, camera or T12" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
                  <select aria-label="Filter camera" className="field" value={camera} onChange={(e) => setCamera(e.target.value)}><option value="">All cameras</option>{cameras.map((v) => <option key={v} value={v}>{v}</option>)}</select>
                  <select aria-label="Filter plate readability" className="field" value={readability} onChange={(e) => setReadability(e.target.value)}>
                    <option value="">Any readability</option><option value="readable">Readable plate (5+)</option><option value="partial">Partial plate (1–4)</option><option value="none">Unreadable plate</option>
                  </select>
                  <select aria-label="Filter registry coverage" className="field" value={coverageFilter} onChange={(e) => setCoverageFilter(e.target.value)}>
                    <option value="">Any registry state</option><option value="searched">Compatible search run</option><option value="no_coverage">No compatible records</option><option value="incomplete">Not searched, plate incomplete</option>
                  </select>
                  <select aria-label="Filter track quality" className="field" value={qualityFilter} onChange={(e) => setQualityFilter(e.target.value)}>
                    <option value="">Any track quality</option><option value="reliable">Reliable tracks</option><option value="review">Tracks to review</option>
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
                        <button onClick={() => onOpenVehicle(vehicle.id)} aria-label={`Inspect ${vehicle.camera_label} track ${vehicle.track_id}`}
                          className="grid w-full grid-cols-[84px_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-canvas lg:grid-cols-[84px_minmax(130px,1fr)_minmax(180px,1.2fr)_minmax(150px,1fr)_minmax(140px,1fr)]">
                          <span className="row-span-3 h-14 w-[84px] overflow-hidden rounded-evidence border border-line bg-slate-100 lg:row-span-1">
                            {vehicle.best_crop && <img loading="lazy" src={artifactUrl(vehicle.best_crop)} alt="" className="h-full w-full object-cover" />}
                          </span>
                          <span className="min-w-0 text-xs">
                            <span className="block truncate font-semibold">{vehicle.camera_label} · <span className="num">T{vehicle.track_id}</span></span>
                            <span className="num block text-2xs text-muted">{seconds(vehicle.first_seen_sec)}–{seconds(vehicle.last_seen_sec)} · {vehicle.frames_tracked} frames</span>
                          </span>
                          <span className="min-w-0"><PlateText text={vehicle.plate} size="sm" /></span>
                          <span className="flex min-w-0 flex-wrap items-center gap-1">
                            <OutcomeBadge outcome={vehicle.outcome} />
                            <LinkBadge status={vehicle.link_status} />
                            {vehicle.track_quality?.tier === "review" ? <Badge tone="amber" title={vehicle.track_quality.reasons.join("; ")}>Review track</Badge>
                              : vehicle.track_quality ? <Badge title="No track-quality concerns were recorded">Reliable track</Badge>
                                : <Badge title="This track came from an older pipeline and has no quality grade">Not graded</Badge>}
                            {vehicle.overridden && <Badge tone="accent">Verified</Badge>}
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
            ) : <Empty title={detail.status === "COMPLETED" ? "No vehicles detected" : active ? "Waiting for the first finished track" : "No analysis yet"}>{detail.status === "COMPLETED" ? "The detector found no trackable vehicle in the usable frames." : active ? "Tracks appear here as they are analysed." : detail.clips.length ? "Run analysis to detect and track vehicles." : "Add at least one CCTV clip to begin."}</Empty>}
          </section>
        </div>

        <div className="min-w-0 space-y-3">
          <section id="recover" className="panel scroll-mt-3">
            <SectionHead step={3} title="Recover and match" note="Multi-frame plate reads compared with compatible registry records." />
            {summary && hasResults ? (
              <>
                <dl className="grid grid-cols-3 gap-px border-b border-line bg-line">
                  {([["Readable", summary.readable_plates], ["Partial", summary.partial_plates], ["No characters", summary.no_plate_chars]] as const).map(([label, value]) => (
                    <div key={label} className="bg-surface px-2.5 py-1.5"><dt className="text-2xs text-muted">{label}</dt><dd className="num text-sm font-semibold">{value}</dd></div>
                  ))}
                </dl>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-xs">
                    <caption className="sr-only">Registry coverage by camera</caption>
                    <thead><tr><th scope="col" className="th">Camera</th><th scope="col" className="th">Format</th><th scope="col" className="th text-right">Compatible</th></tr></thead>
                    <tbody>
                      {summary.coverage.map((row) => (
                        <tr key={row.clip_id}><td className="td">{row.camera_label}</td><td className="td">{row.format_label}</td><td className={`td num text-right ${row.status === "no_coverage" ? "font-semibold text-amber-900" : ""}`}>{row.compatible_records.toLocaleString()}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="space-y-1 px-3 py-2 text-2xs text-muted">
                  <li><span className="font-medium text-ink">Registry:</span> {summary.registry.note}</li>
                  <li><span className="font-medium text-ink">Scores:</span> {summary.score_note}</li>
                </ul>
              </>
            ) : <Empty title="No plate evidence yet">Plate recovery runs during analysis.</Empty>}
          </section>

          <section id="review" className="panel scroll-mt-3">
            <SectionHead step={4} title="Review and report" />
            <div className="space-y-1.5 p-2">
              <button className="btn w-full justify-start" disabled={!vehicles.length} onClick={() => vehicles.length && onOpenVehicle((nextFlagged ?? [...vehicles].sort((a, b) => b.known_chars - a.known_chars)[0]).id)}>
                <ScanSearch size={15} /> {nextFlagged ? `Inspect next flagged track (T${nextFlagged.track_id})` : "Inspect best plate read"}<ArrowRight size={13} className="ml-auto" aria-hidden="true" />
              </button>
              <button className="btn w-full justify-start" onClick={onOpenTrace}>
                <Share2 size={15} /> {(summary?.possible_links ?? 0) > 0 ? `Review ${summary.possible_links} possible link${summary.possible_links === 1 ? "" : "s"}` : "Open cross-camera trace"}<ArrowRight size={13} className="ml-auto" aria-hidden="true" />
              </button>
              <button className="btn w-full justify-start" disabled={!hasResults} onClick={onOpenReports}>
                <FileText size={15} /> Preview and download reports<ArrowRight size={13} className="ml-auto" aria-hidden="true" />
              </button>
            </div>
            {summary && (
              <ul className="space-y-1 border-t border-line px-3 py-2 text-2xs text-muted">
                <li><span className="font-medium text-ink">Temporal validation:</span> {summary.temporal_note}</li>
                <li><span className="font-medium text-ink">Cross-camera:</span> {summary.cross_camera_note}</li>
              </ul>
            )}
            <details className="border-t border-line">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Audit log <span className="num font-normal text-muted">{detail.audit.length}</span></summary>
              <ol className="max-h-64 divide-y divide-line overflow-y-auto border-t border-line">
                {[...detail.audit].reverse().map((entry) => (
                  <li key={entry.id} className="px-3 py-1.5 text-2xs">
                    <div className="font-medium">{actionLabel(entry.action)}</div>
                    <div className="num text-muted">{new Date(entry.created_at).toLocaleString()} · {entry.actor}</div>
                    {entry.note && <div className="break-words text-muted">{entry.note}</div>}
                  </li>
                ))}
              </ol>
            </details>
          </section>
        </div>
      </div>
    </div>
  );
}
