import { Activity, AlertTriangle, ArrowRight, Camera, ChevronRight, CircleHelp, Database, FolderOpen, Lightbulb, Plus, Search, Share2, ShieldAlert, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, artifactUrl, progressUrl } from "../api/client";
import { GuidedTour } from "../components/GuidedTour";
import { InfoTip } from "../components/InfoTip";
import { InvestigationTable } from "../components/InvestigationTable";
import { Badge, Empty, Loading, Notice, OUTCOMES, OutcomeBadge, PlateText, clock, relativeTime, seconds } from "../components/ui";
import { actionLabel, activityByDay, analysisState, coverageWarnings, insights, isActiveRun, lastActivity, nextStep, outcomeTotals, recentActivity, reviewState, workload, type GuideAction } from "../lib/overview";
import type { Overview } from "../lib/useOverview";
import type { CaseDetail, CaseSummary, Health, Keyframe, ProgressEvent, VehicleDetail } from "../types";

const MAX_WARNINGS = 4;
const TABLE_FILTERS = [
  { id: "all", label: "All states", test: () => true },
  { id: "running", label: "Running", test: isActiveRun },
  { id: "waiting", label: "Awaiting analysis", test: (item: CaseDetail) => !isActiveRun(item) && !item.has_completed_run },
  { id: "review", label: "To review", test: (item: CaseDetail) => reviewState(item).tone === "amber" },
  { id: "coverage", label: "Coverage gap", test: (item: CaseDetail) => item.summary?.coverage_status !== "covered" && Boolean(item.summary?.coverage?.length) },
];

interface Props {
  overview: Overview;
  ready: boolean;
  failed: boolean;
  cases: CaseSummary[];
  health: Health | null;
  onNewCase: () => void;
  onOpenCase: (id: string) => void;
  onOpenVehicle: (id: string, caseId?: string) => void;
  onOpenTrace: (id: string) => void;
  onOpenRegistry: () => void;
  onRetry: () => void;
}

function Heading({ id, title, tip, right }: { id: string; title: string; tip?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 px-3.5 pt-3">
      <h2 id={id} className="flex items-center gap-0.5 text-[13px] font-semibold text-white">{title}{tip && <InfoTip label={title.toLowerCase()}>{tip}</InfoTip>}</h2>
      {right}
    </div>
  );
}

function PipelineStrip({ data, loading }: { data: ReturnType<typeof workload>; loading: boolean }) {
  const steps = [
    { name: "Ingest", value: data.clips, note: "clips stored and hashed", help: "CCTV clips added to VITRA. Each gets a SHA-256 fingerprint so tampering can be detected." },
    { name: "Detect", value: data.tracks, note: "vehicles tracked", help: "A track is one vehicle followed through one clip." },
    { name: "Recover", value: data.readable + data.partial, note: "plates with characters", help: "Tracks where at least one plate character could be read across frames." },
    { name: "Match", value: data.compared, note: `compared, ${data.notSearched} not searched`, help: "Readable plates compared with compatible registry records. Not searched means the registry has no records in that plate format." },
    { name: "Review", value: data.tracksReview + data.possibleLinks, note: "items need a person", help: "Flagged tracks and possible cross-camera links waiting for an investigator." },
  ];
  return (
    <ol data-tour="pipeline" aria-label="Evidence pipeline across all investigations" className="grid divide-y divide-line rounded-evidence border border-line bg-surface sm:grid-cols-5 sm:divide-x sm:divide-y-0">
      {steps.map((step, index) => (
        <li key={step.name} className="flex items-center gap-2 px-3.5 py-2 sm:block sm:py-2.5">
          <div className="flex w-24 shrink-0 items-center gap-1 text-xs font-semibold text-accent-soft sm:w-auto">
            <span className="num flex h-[18px] w-[18px] items-center justify-center rounded-full bg-accent-tint text-[10px]">{index + 1}</span>{step.name}
            <InfoTip label={step.name}>{step.help}</InfoTip>
            {index < steps.length - 1 && <ChevronRight size={14} aria-hidden="true" className="ml-auto hidden text-slate-500 lg:block" />}
          </div>
          <div className="num w-12 shrink-0 text-base font-semibold text-white sm:w-auto sm:text-xl">{loading ? "–" : step.value.toLocaleString()}</div>
          <div className="min-w-0 text-2xs text-muted">{step.note}</div>
        </li>
      ))}
    </ol>
  );
}

function StatTile({ icon: Icon, tone, label, value, note, help, loading }: { icon: LucideIcon; tone: string; label: string; value: number; note: string; help: string; loading: boolean }) {
  return (
    <div className="panel flex min-w-0 flex-col p-3">
      <div className="flex items-start justify-between">
        <span className={`flex h-7 w-7 items-center justify-center rounded-md border ${tone}`}><Icon size={14} aria-hidden="true" /></span>
        <InfoTip label={label}>{help}</InfoTip>
      </div>
      <div className="num mt-1.5 text-2xl font-semibold text-white">{loading ? "–" : value.toLocaleString()}</div>
      <div className="text-xs font-medium text-ink">{label}</div>
      <div className="text-2xs leading-4 text-muted">{loading ? "Loading" : note}</div>
    </div>
  );
}

function Ring({ value }: { value: number }) {
  const circumference = 2 * Math.PI * 22;
  return (
    <svg width="58" height="58" viewBox="0 0 58 58" aria-hidden="true" className="shrink-0 -rotate-90">
      <circle cx="29" cy="29" r="22" fill="none" stroke="#3F385E" strokeWidth="5" />
      <circle cx="29" cy="29" r="22" fill="none" stroke="#9C8CFF" strokeWidth="5" strokeLinecap="round" strokeDasharray={`${circumference * value} ${circumference}`} className="transition-all duration-700" />
    </svg>
  );
}

function PlateEvidence({ details, loading }: { details: CaseDetail[]; loading: boolean }) {
  const totals = details.reduce((sum, item) => ({
    tracks: sum.tracks + (item.summary?.tracks ?? 0),
    readable: sum.readable + (item.summary?.readable_plates ?? 0),
    partial: sum.partial + (item.summary?.partial_plates ?? 0),
    none: sum.none + (item.summary?.no_plate_chars ?? 0),
  }), { tracks: 0, readable: 0, partial: 0, none: 0 });
  const rows = [
    { label: "Readable plate", note: "5+ characters", value: totals.readable, bar: "bg-[#9C8CFF]" },
    { label: "Partial plate", note: "1 to 4 characters", value: totals.partial, bar: "bg-signal" },
    { label: "No characters", note: "plate unreadable", value: totals.none, bar: "bg-slate-400" },
  ];
  return (
    <section aria-labelledby="plate-evidence" className="panel h-full pb-3">
      <Heading id="plate-evidence" title="Plate evidence" tip="How much of each tracked vehicle's plate could be read. Unknown characters stay as ? and are never guessed." right={<span className="text-2xs text-muted">All tracks</span>} />
      {!loading && !totals.tracks ? <Empty title="No plate evidence yet">Run an analysis to see plate reads.</Empty> : (
        <ul className="mt-2 space-y-2.5 px-3.5">
          {rows.map((row) => {
            const share = totals.tracks ? row.value / totals.tracks : 0;
            return (
              <li key={row.label}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 text-xs font-medium text-ink">{row.label}: <span className="num">{loading ? "–" : row.value.toLocaleString()}</span> <span className="text-2xs font-normal text-muted">{row.note}</span></span>
                  <span className="num shrink-0 text-xs text-muted">{loading ? "–" : `${Math.round(share * 100)}%`}</span>
                </div>
                <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-slate-100"><span className={`block h-full rounded-full transition-all duration-700 ${row.bar}`} style={{ width: `${share * 100}%` }} /></span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ActivityChart({ details }: { details: CaseDetail[] }) {
  const [range, setRange] = useState(14);
  const days = activityByDay(details, range);
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...days.map((day) => day.value), 1);
  const activeDays = days.filter((day) => day.value > 0).length;
  const total = days.reduce((sum, day) => sum + day.value, 0);
  const label = (date: Date) => date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const focus = hover === null ? null : days[hover];
  return (
    <section aria-labelledby="activity-chart" className="panel flex h-full flex-col pb-3">
      <Heading id="activity-chart" title="Case activity" tip="Every action in the audit log, such as adding evidence, running analysis or reviewing a link, counted per day."
        right={<select aria-label="Activity time range" className="field !min-h-7 !w-auto !py-0.5" value={range} onChange={(event) => { setRange(Number(event.target.value)); setHover(null); }}><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option></select>} />
      <div className="num px-3.5 text-2xs text-muted" aria-live="polite">{focus ? `${label(focus.date)}: ${focus.value} events` : `${total} audit events`}</div>
      {activeDays >= 2 ? (
        <div className="mt-1 flex-1 px-3.5">
          <div className="flex h-[92px] items-end gap-px border-b border-slate-400" onMouseLeave={() => setHover(null)} aria-hidden="true">
            {days.map((day, index) => (
              <div key={index} className={`flex h-full min-w-0 flex-1 items-end ${hover === index ? "bg-accent-tint" : ""}`} onMouseEnter={() => setHover(index)} title={`${label(day.date)}: ${day.value} events`}>
                <div className="w-full rounded-t-sm bg-[#9C8CFF]" style={{ height: `${(day.value / max) * 100}%`, minHeight: day.value ? 2 : 0 }} />
              </div>
            ))}
          </div>
          <div className="num mt-1 flex justify-between text-2xs text-muted" aria-hidden="true"><span>{label(days[0].date)}</span><span>Today</span></div>
          <table className="sr-only">
            <caption>Audit events per day for the last {range} days</caption>
            <tbody>{days.map((day) => <tr key={day.date.toISOString()}><th scope="row">{label(day.date)}</th><td>{day.value}</td></tr>)}</tbody>
          </table>
        </div>
      ) : <div className="flex flex-1 items-center justify-center px-3.5 py-3 text-center text-2xs text-muted">{total ? `${total} event${total === 1 ? "" : "s"} on one day. The chart appears once events span two days.` : "No activity in this period."}</div>}
    </section>
  );
}

function InsightCards({ details, overview, run }: { details: CaseDetail[]; overview: Overview; run: (action: GuideAction) => void }) {
  const list = insights(details, overview.coverage);
  return (
    <section data-tour="insights" aria-labelledby="insights-title">
      <h2 id="insights-title" className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-white"><Lightbulb size={15} aria-hidden="true" className="text-signal" /> What needs your attention <span className="num font-normal text-muted">{list.length}</span></h2>
      {list.length ? (
        <ul tabIndex={0} aria-label="Findings, scroll sideways for more" className="flex snap-x gap-2.5 overflow-x-auto pb-2">
          {list.map((item) => (
            <li key={item.key} className={`flex min-h-[122px] w-[258px] shrink-0 snap-start flex-col rounded-evidence border p-3 ${item.tone === "warn" ? "border-accent-line bg-accent-tint" : "border-line bg-surface"}`}>
              <div className="flex items-start justify-between">
                <span className={`flex h-6 w-6 items-center justify-center rounded border ${item.tone === "warn" ? "border-accent-soft/50 text-accent-soft" : "border-line text-muted"}`}><Lightbulb size={13} aria-hidden="true" /></span>
                <InfoTip label={item.lead}>{item.help}</InfoTip>
              </div>
              <p className="mt-1 flex-1 text-[13px] leading-[18px] text-ink"><strong className="font-semibold text-white">{item.lead}</strong> {item.text}</p>
              <button className="mt-2 inline-flex min-h-7 items-center gap-1 self-start rounded text-xs font-semibold text-accent-soft hover:text-white" onClick={() => run(item.action)}>{item.action.label}<ArrowRight size={13} aria-hidden="true" /></button>
            </li>
          ))}
        </ul>
      ) : <div className="panel px-3.5 py-4 text-xs text-muted">Nothing needs attention. New findings appear here after analysis.</div>}
    </section>
  );
}

function AllInvestigations({ details, loading }: { details: CaseDetail[]; loading: boolean }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("all");
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rule = TABLE_FILTERS.find((item) => item.id === state) ?? TABLE_FILTERS[0];
    return details
      .filter((item) => rule.test(item) && (!needle || item.title.toLowerCase().includes(needle)
        || (item.clips ?? []).some((clip) => clip.camera_label.toLowerCase().includes(needle) || clip.filename.toLowerCase().includes(needle))))
      .sort((a, b) => new Date(lastActivity(b)).getTime() - new Date(lastActivity(a)).getTime());
  }, [details, query, state]);
  return (
    <section data-tour="table" aria-labelledby="all-investigations">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 id="all-investigations" className="mr-auto text-[13px] font-semibold text-white">All investigations <span className="num ml-1 rounded border border-accent-line px-1.5 py-px text-2xs text-accent-soft">{visible.length}</span></h2>
        <select aria-label="Filter investigations by state" className="field !w-auto" value={state} onChange={(event) => setState(event.target.value)}>
          {TABLE_FILTERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <label className="relative w-full sm:w-56">
          <Search size={14} aria-hidden="true" className="absolute left-2 top-2 text-muted" />
          <input aria-label="Search investigations" className="field pl-7" placeholder="Search case, camera or file" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {(query || state !== "all") && <button className="btn" onClick={() => { setQuery(""); setState("all"); }}>Reset</button>}
      </div>
      <div className="panel overflow-hidden">
        {loading && !details.length ? <Loading>Loading investigations…</Loading>
          : visible.length ? <InvestigationTable items={visible} /> : <Empty title="No investigations match">Clear the search or choose another state.</Empty>}
      </div>
    </section>
  );
}

function OutcomeChart({ details }: { details: CaseDetail[] }) {
  const rows = outcomeTotals(details);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const max = Math.max(...rows.map((row) => row.value), 1);
  const analysed = details.filter((item) => item.has_completed_run).length;
  return (
    <section aria-labelledby="outcome-chart" className="panel pb-2">
      <Heading id="outcome-chart" title="Track outcomes" tip="The result for every tracked vehicle. Open the i beside an outcome for what it means." />
      <p className="px-3.5 text-2xs text-muted">Tracks per outcome across {analysed} analysed case{analysed === 1 ? "" : "s"}</p>
      {total ? (
        <table className="mt-1 w-full border-collapse text-xs">
          <caption className="sr-only">Track count and share by outcome</caption>
          <tbody>
            {rows.map((row) => (
              <tr key={row.outcome} className="hover:bg-raised">
                <th scope="row" className="w-[50%] py-0.5 pl-3.5 pr-1 text-left text-2xs font-medium text-ink"><span className="inline-flex items-center">{OUTCOMES[row.outcome].label}<InfoTip label={OUTCOMES[row.outcome].label}>{OUTCOMES[row.outcome].help}</InfoTip></span></th>
                <td className="py-0.5"><span className="block h-2 rounded-r bg-[#9C8CFF]" style={{ width: `${(row.value / max) * 100}%`, minWidth: row.value ? 2 : 0 }} /></td>
                <td className="num w-[74px] whitespace-nowrap py-0.5 pl-2 pr-3.5 text-right text-2xs">{row.value} <span className="text-muted">{Math.round((row.value / total) * 100)}%</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <Empty title="No track outcomes yet">Run an analysis to populate this chart.</Empty>}
    </section>
  );
}

function RegistryHealth({ overview, onOpenRegistry, onOpenCase }: { overview: Overview; onOpenRegistry: () => void; onOpenCase: (id: string) => void }) {
  const warnings = coverageWarnings(overview.details);
  const data = overview.coverage;
  return (
    <section data-tour="registry" aria-labelledby="registry-health" className="panel overflow-hidden">
      <Heading id="registry-health" title="Registry health" tip="The registry is the vehicle list plates are compared with. A camera's plate format must exist here before its plates can be searched."
        right={<button className="btn" onClick={onOpenRegistry}><Database size={13} /> Manage</button>} />
      {overview.loading && !data ? <Loading>Loading registry…</Loading> : !data ? <Empty title="Registry coverage unavailable">The coverage service did not respond.</Empty> : (
        <>
          <div className="px-3.5 py-2">
            <div className="num text-2xl font-semibold text-white">{data.total.toLocaleString()} <span className="font-sans text-xs font-normal text-muted">entries</span></div>
            <p className="text-2xs leading-4 text-muted">{data.note}</p>
          </div>
          <table className="w-full border-collapse border-t border-line text-xs">
            <caption className="sr-only">Compatible registry records by camera plate format</caption>
            <thead><tr><th scope="col" className="th !pl-3.5">Camera plate format</th><th scope="col" className="th !pr-3.5 text-right">Compatible</th></tr></thead>
            <tbody>
              {data.formats.map((row) => (
                <tr key={row.plate_format}>
                  <td className="td !pl-3.5">{row.label}</td>
                  <td className="td num !pr-3.5 text-right">{row.compatible_records ? row.compatible_records.toLocaleString() : <span className="inline-flex items-center gap-1 font-semibold text-amber-900"><AlertTriangle size={12} aria-hidden="true" />0</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {warnings.length > 0 && (
            <div className="space-y-1 bg-amber-50 px-3.5 py-2 text-2xs text-amber-950">
              <div className="flex items-center gap-1 font-semibold"><AlertTriangle size={13} aria-hidden="true" /> Coverage warnings</div>
              <ul className="space-y-1">
                {warnings.slice(0, MAX_WARNINGS).map((item) => (
                  <li key={item.key}><button className="text-left underline underline-offset-2" onClick={() => onOpenCase(item.caseId)}>{item.caseTitle}</button>: {item.message}</li>
                ))}
              </ul>
              {warnings.length > MAX_WARNINGS && <div>{warnings.length - MAX_WARNINGS} more in Investigations.</div>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function LatestEvidence({ details, onOpenVehicle }: { details: CaseDetail[]; onOpenVehicle: Props["onOpenVehicle"] }) {
  const source = useMemo(() => [...details]
    .filter((item) => item.has_completed_run && item.vehicle_count > 0 && !isActiveRun(item))
    .sort((a, b) => new Date(lastActivity(b)).getTime() - new Date(lastActivity(a)).getTime())[0], [details]);
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const sourceId = source?.id;
  const version = source?.updated_at;

  useEffect(() => {
    if (!sourceId) return;
    let live = true;
    setState("loading");
    api.vehicles(sourceId)
      .then(({ vehicles }) => {
        const best = [...vehicles].sort((a, b) => b.known_chars - a.known_chars || b.frames_tracked - a.frames_tracked)[0];
        return best ? api.vehicle(sourceId, best.id) : null;
      })
      .then((value) => { if (live) { setVehicle(value); setState("ready"); } })
      .catch(() => { if (live) setState("failed"); });
    return () => { live = false; };
  }, [sourceId, version]);

  const frame: Keyframe | undefined = vehicle?.keyframes.find((item) => item.plate_raw) ?? vehicle?.keyframes[0];
  return (
    <section aria-labelledby="latest-evidence" className="panel overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5">
        <h2 id="latest-evidence" className="flex items-center text-[13px] font-semibold text-white">Latest evidence<InfoTip label="latest evidence">The clearest plate read from your most recently analysed case. Click it to inspect every frame.</InfoTip></h2>
        {vehicle && <Badge tone={vehicle.clip.synthetic ? "amber" : "slate"}>{vehicle.clip.synthetic ? "Demo evidence" : "Case evidence"}</Badge>}
      </div>
      {!source ? <Empty title="No analysed evidence yet">A source frame and plate crop appear here after the first analysis.</Empty>
        : state === "loading" ? <Loading>Loading evidence…</Loading>
          : state === "failed" ? <Empty title="Evidence preview unavailable">Open the investigation to view its tracks.</Empty>
            : vehicle && frame ? (
              <button className="block w-full text-left hover:bg-raised" onClick={() => onOpenVehicle(vehicle.id, source.id)}>
                <span className="relative block bg-shell">
                  <img src={artifactUrl(frame.frame)} alt={`Annotated source frame for track ${vehicle.track_id}`} className="aspect-video w-full object-contain" />
                  <span className="num absolute bottom-1 left-1 rounded bg-shell/90 px-1.5 py-0.5 text-2xs text-shell-text">{seconds(frame.timestamp_sec)} · frame {frame.frame_idx}</span>
                </span>
                <span className="block space-y-1.5 p-3">
                  <span className="block truncate text-xs font-semibold text-white">{source.title}</span>
                  <span className="block text-2xs text-muted">{vehicle.camera_label} · Track {vehicle.track_id}</span>
                  {frame.plate_raw && <img src={artifactUrl(frame.plate_raw)} alt="Raw plate crop" className="h-10 max-w-full rounded border border-line bg-slate-100 object-contain [image-rendering:pixelated]" />}
                  <span className="flex flex-wrap items-center gap-1.5"><PlateText text={vehicle.plate} size="sm" /><OutcomeBadge outcome={vehicle.outcome} /></span>
                  <span className="inline-flex items-center gap-1 text-2xs font-semibold text-accent-soft">Open in inspector <ArrowRight size={13} aria-hidden="true" /></span>
                </span>
              </button>
            ) : <Empty title="No keyframes stored" />}
    </section>
  );
}

function QueueRow({ item, onOpenCase }: { item: CaseDetail; onOpenCase: (id: string) => void }) {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const running = isActiveRun(item);
  useEffect(() => {
    if (!running) return;
    const source = new EventSource(progressUrl(item.id));
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as ProgressEvent;
      setProgress(event);
      if (event.status !== "RUNNING") source.close();
    };
    source.onerror = () => source.close();
    return () => source.close();
  }, [item.id, running]);
  const state = analysisState(item);
  return (
    <li className="space-y-1 px-3.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <button className="min-w-0 truncate text-left text-xs font-semibold text-accent-soft underline-offset-2 hover:underline" onClick={() => onOpenCase(item.id)}>{item.title}</button>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      {running && (
        <>
          <div className="h-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label={`Progress for ${item.title}`} aria-valuenow={progress?.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-[#9C8CFF] transition-all" style={{ width: `${progress?.percent ?? 0}%` }} />
          </div>
          <div className="flex justify-between gap-2 text-2xs text-muted">
            <span className="truncate">{progress?.stage_label ?? "Connecting"}</span>
            <span className="num shrink-0">{(progress?.percent ?? 0).toFixed(0)}%{progress?.eta_sec != null ? ` · about ${clock(progress.eta_sec)} left` : ""}</span>
          </div>
        </>
      )}
    </li>
  );
}

function ProcessingQueue({ details, onOpenCase }: { details: CaseDetail[]; onOpenCase: (id: string) => void }) {
  const items = details.filter((item) => isActiveRun(item) || item.status === "FAILED" || item.status === "CANCELLED"
    || (!item.has_completed_run && item.clip_count > 0));
  items.sort((a, b) => Number(isActiveRun(b)) - Number(isActiveRun(a)));
  return (
    <section aria-labelledby="processing-queue" className="panel pb-1">
      <Heading id="processing-queue" title="Processing queue" tip="Analyses that are running, waiting to start, failed or were cancelled." right={<span className="num text-xs text-muted">{items.length}</span>} />
      {items.length ? <ul className="mt-1 divide-y divide-line">{items.map((item) => <QueueRow key={item.id} item={item} onOpenCase={onOpenCase} />)}</ul>
        : <Empty title="Queue is clear">No analysis is running, waiting, failed or cancelled.</Empty>}
    </section>
  );
}

function RecentActivity({ details, onOpenCase }: { details: CaseDetail[]; onOpenCase: (id: string) => void }) {
  const entries = recentActivity(details);
  return (
    <section aria-labelledby="recent-activity" className="panel pb-1">
      <Heading id="recent-activity" title="Recent activity" tip="The latest entries from each case's permanent audit log." right={<span className="text-2xs text-muted">Audit log</span>} />
      {entries.length ? (
        <ol className="mt-1 divide-y divide-line">
          {entries.map((entry) => (
            <li key={`${entry.caseId}-${entry.id}`} className="px-3.5 py-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 text-xs font-medium text-ink">{actionLabel(entry.action)}</span>
                <time dateTime={entry.created_at} title={new Date(entry.created_at).toLocaleString()} className="num shrink-0 text-2xs text-muted">{relativeTime(entry.created_at)}</time>
              </div>
              <button className="block max-w-full truncate text-left text-2xs text-muted underline-offset-2 hover:underline" onClick={() => onOpenCase(entry.caseId)}>{entry.caseTitle} · {entry.actor}</button>
            </li>
          ))}
        </ol>
      ) : <Empty title="No activity yet">Case, evidence and review events appear here.</Empty>}
    </section>
  );
}

function FirstRun({ onNewCase }: { onNewCase: () => void }) {
  const steps = ["Add CCTV clips and record their SHA-256", "Detect and track each vehicle", "Recover plate characters across frames", "Compare readable plates with the registry", "Review evidence and export a report"];
  return (
    <section className="panel px-4 py-6">
      <h2 className="text-sm font-semibold text-white">Start your first investigation</h2>
      <p className="mt-0.5 max-w-xl text-xs text-muted">No cases exist yet, so there is nothing to summarise. Each investigation follows the same evidence path.</p>
      <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {steps.map((step, index) => <li key={step} className="rounded-evidence border border-line bg-raised px-2.5 py-2 text-xs"><span className="num mr-1.5 font-semibold text-accent-soft">{index + 1}</span>{step}</li>)}
      </ol>
      <button className="btn btn-primary mt-3" onClick={onNewCase}><Plus size={15} /> New investigation</button>
    </section>
  );
}

export default function Dashboard({ overview, ready, failed, cases, onNewCase, onOpenCase, onOpenVehicle, onOpenTrace, onOpenRegistry, onRetry }: Props) {
  const { details } = overview;
  const data = useMemo(() => workload(details), [details]);
  const busy = !ready || (overview.loading && cases.length > 0);
  const empty = ready && !failed && cases.length === 0;
  const [touring, setTouring] = useState(false);
  const step = nextStep(details);
  const newest = useMemo(() => details.map(lastActivity).filter(Boolean).sort().pop(), [details]);
  const readableShare = data.tracks ? data.readable / data.tracks : 0;

  const run = (action: GuideAction) => {
    if (action.kind === "new") onNewCase();
    if (action.kind === "registry") onOpenRegistry();
    if (action.kind === "case" && action.caseId) onOpenCase(action.caseId);
    if (action.kind === "trace" && action.caseId) onOpenTrace(action.caseId);
  };

  return (
    <>
      {touring && <GuidedTour onClose={() => setTouring(false)} />}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-white">Investigation overview <span className="ml-1.5 align-middle text-xs font-normal text-muted">{newest ? `Updated ${relativeTime(newest)}` : ""}</span></h1>
          <p className="text-[13px] text-muted">What is in progress, what needs you, and whether the registry can support each search.</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button className="btn" onClick={() => setTouring(true)} disabled={empty}><CircleHelp size={15} /> Take the tour</button>
          <button className="btn btn-primary" onClick={onNewCase}><Plus size={15} /> New investigation</button>
        </div>
      </header>

      {failed && !cases.length && <Notice tone="crimson" live="alert" title="Could not reach the case service" action={<button className="btn" onClick={onRetry}>Retry</button>}>Dashboard figures are unavailable until the API responds.</Notice>}
      {overview.failed.length > 0 && <Notice tone="amber" live="alert" title="Partial results">{overview.failed.length} investigation(s) could not be loaded, so totals exclude: {overview.failed.join(", ")}.</Notice>}

      {empty ? <FirstRun onNewCase={onNewCase} /> : (
        <>
          <section data-tour="next" aria-labelledby="next-step" className="flex flex-wrap items-center gap-3 rounded-evidence border border-accent bg-gradient-to-r from-accent-tint to-surface px-4 py-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-signal text-[#14101F]"><ArrowRight size={18} aria-hidden="true" /></span>
            <div className="min-w-[200px] flex-1">
              <div className="text-2xs font-semibold uppercase tracking-wide text-signal">Your next step</div>
              <h2 id="next-step" className="text-[15px] font-semibold text-white">{busy ? "Checking your casework…" : step.title}</h2>
              {!busy && <p className="text-xs text-[#D6D2E8]">{step.body}</p>}
            </div>
            {!busy && <button className="btn btn-primary !min-h-9 !px-4" onClick={() => run(step.action)}>{step.action.label}<ArrowRight size={15} aria-hidden="true" /></button>}
          </section>

          <PipelineStrip data={data} loading={busy} />

          <section data-tour="stats" aria-label="Workload summary" className="grid gap-3 md:grid-cols-2 xl:grid-cols-12">
            <div className="grid gap-3 sm:grid-cols-2 md:col-span-2 xl:col-span-3 xl:grid-cols-1">
              <div className="panel flex items-start justify-between px-3.5 py-3">
                <div><div className="num text-3xl font-semibold text-white">{busy ? "–" : data.tracks.toLocaleString()}</div><div className="text-[13px] text-muted">Total vehicle tracks</div></div>
                <InfoTip label="vehicle tracks">A track is one vehicle followed through one clip. The same vehicle on two cameras counts as two tracks until a link is confirmed.</InfoTip>
              </div>
              <div className="panel flex items-center gap-3 px-3.5 py-3">
                <Ring value={readableShare} />
                <div className="min-w-0 flex-1"><div className="num text-xl font-semibold text-white">{busy ? "–" : `${Math.round(readableShare * 100)}%`}</div><div className="text-xs text-muted">Tracks with a readable plate</div></div>
                <InfoTip label="readable plate share">The share of tracks where at least 5 plate characters could be read across frames.</InfoTip>
              </div>
            </div>
            <div className="xl:col-span-3"><PlateEvidence details={details} loading={busy} /></div>
            <div className="grid grid-cols-2 gap-3 xl:col-span-3">
              <StatTile loading={busy} icon={FolderOpen} tone="border-accent-soft/50 text-accent-soft" label="Active cases" value={data.activeCases} note={`of ${details.length} · ${data.runningCases} running`} help="Cases with something still to do: running, not analysed yet, or waiting for a review decision." />
              <StatTile loading={busy} icon={Camera} tone="border-emerald-300 text-emerald-800" label="Clips waiting" value={data.clipsAwaiting} note={data.clipsInAnalysis ? `${data.clipsInAnalysis} in analysis` : `of ${data.clips} clips`} help="CCTV clips that have been added but not analysed yet." />
              <StatTile loading={busy} icon={ShieldAlert} tone="border-amber-400 text-amber-800" label="Tracks to review" value={data.tracksReview} note={data.tracksUngraded ? `${data.tracksUngraded} ungraded` : `of ${data.tracks} tracks`} help="Tracks that may be unreliable, for example very short or heavily covered. Ungraded tracks came from older analysis runs." />
              <StatTile loading={busy} icon={Share2} tone="border-rose-300 text-rose-800" label="Cases with links" value={data.casesWithLinks} note={`${data.possibleLinks} link${data.possibleLinks === 1 ? "" : "s"} to review`} help="Cases where the same vehicle may appear on more than one camera. A person must confirm each link." />
            </div>
            <div className="md:col-span-2 xl:col-span-3"><ActivityChart details={details} /></div>
          </section>

          <InsightCards details={details} overview={overview} run={run} />
          <AllInvestigations details={details} loading={busy} />

          <div className="grid items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
            <div className="space-y-3"><OutcomeChart details={details} /><ProcessingQueue details={details} onOpenCase={onOpenCase} /></div>
            <RegistryHealth overview={overview} onOpenRegistry={onOpenRegistry} onOpenCase={onOpenCase} />
            <div className="space-y-3 md:col-span-2 xl:col-span-1"><LatestEvidence details={details} onOpenVehicle={onOpenVehicle} /><RecentActivity details={details} onOpenCase={onOpenCase} /></div>
          </div>
          <p className="flex items-center gap-1.5 text-2xs text-muted"><Activity size={12} aria-hidden="true" /> All figures come from your current case data. Match scores are ranking values, not probabilities.</p>
        </>
      )}
    </>
  );
}
