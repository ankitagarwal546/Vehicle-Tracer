/** Derives dashboard figures from the case API. Nothing here is estimated or hardcoded. */
import type { Tone } from "../components/ui";
import { OUTCOME_ORDER } from "../components/ui";
import type { AuditEntry, CaseDetail, CaseSummary, Outcome } from "../types";

export const isActiveRun = (item: CaseSummary) => item.running || item.status === "QUEUED" || item.status === "RUNNING";

export function analysisState(item: CaseSummary): { label: string; tone: Tone } {
  if (isActiveRun(item)) return { label: item.status === "QUEUED" ? "Queued" : "Analysing", tone: "accent" };
  if (item.status === "FAILED") return { label: item.has_completed_run ? "Failed, earlier results kept" : "Failed", tone: "crimson" };
  if (item.status === "CANCELLED") return { label: item.has_completed_run ? "Cancelled, earlier results kept" : "Cancelled", tone: "amber" };
  if (item.status === "COMPLETED") return item.stale ? { label: "Analysed, older pipeline", tone: "amber" } : { label: "Analysed", tone: "emerald" };
  return item.clip_count ? { label: "Awaiting analysis", tone: "amber" } : { label: "No clips", tone: "slate" };
}

export function reviewState(item: CaseDetail): { label: string; tone: Tone } {
  if (!item.has_completed_run) return { label: "Not started", tone: "slate" };
  const links = item.summary?.possible_links ?? 0;
  const tracks = item.summary?.tracks_review ?? 0;
  const parts = [links && `${links} link${links === 1 ? "" : "s"}`, tracks && `${tracks} track${tracks === 1 ? "" : "s"}`].filter(Boolean);
  return parts.length ? { label: `${parts.join(", ")} to review`, tone: "amber" } : { label: "Nothing flagged", tone: "slate" };
}

export const lastActivity = (item: CaseDetail) => {
  const times = [item.updated_at, ...(item.audit ?? []).map((entry) => entry.created_at)].filter(Boolean);
  return times.reduce((latest, value) => (new Date(value).getTime() > new Date(latest).getTime() ? value : latest), times[0]);
};

const unanalysedClips = (item: CaseDetail) => (item.clips ?? []).filter((clip) => !Object.keys(clip.processing ?? {}).length).length;

const hasOutstandingWork = (item: CaseDetail) => isActiveRun(item)
  || unanalysedClips(item) > 0
  || (!item.has_completed_run && item.clip_count > 0)
  || (item.summary?.possible_links ?? 0) > 0
  || (item.summary?.tracks_review ?? 0) > 0;

export function workload(details: CaseDetail[]) {
  const sum = (pick: (item: CaseDetail) => number) => details.reduce((total, item) => total + pick(item), 0);
  const waiting = details.filter((item) => !isActiveRun(item));
  return {
    activeCases: details.filter(hasOutstandingWork).length,
    runningCases: details.filter(isActiveRun).length,
    clipsAwaiting: waiting.reduce((total, item) => total + unanalysedClips(item), 0),
    clipsInAnalysis: details.filter(isActiveRun).reduce((total, item) => total + unanalysedClips(item), 0),
    tracksReview: sum((item) => item.summary?.tracks_review ?? 0),
    tracksUngraded: sum((item) => Math.max((item.summary?.tracks ?? 0) - (item.summary?.tracks_reliable ?? 0) - (item.summary?.tracks_review ?? 0), 0)),
    casesWithLinks: details.filter((item) => (item.summary?.possible_links ?? 0) > 0).length,
    possibleLinks: sum((item) => item.summary?.possible_links ?? 0),
    clips: sum((item) => item.clip_count),
    tracks: sum((item) => item.summary?.tracks ?? 0),
    readable: sum((item) => item.summary?.readable_plates ?? 0),
    partial: sum((item) => item.summary?.partial_plates ?? 0),
    compared: sum((item) => (item.summary?.plate_candidates ?? 0) + (item.summary?.ambiguous ?? 0) + (item.summary?.no_registry_match ?? 0)),
    notSearched: sum((item) => item.summary?.no_registry_coverage ?? 0),
    analysedCases: details.filter((item) => item.has_completed_run).length,
  };
}

const SUMMARY_KEY: Record<Outcome, "plate_candidates" | "ambiguous" | "no_registry_match" | "no_registry_coverage" | "insufficient_plate" | "unreadable_plate"> = {
  PLATE_CANDIDATE: "plate_candidates",
  AMBIGUOUS: "ambiguous",
  NO_REGISTRY_MATCH: "no_registry_match",
  NO_REGISTRY_COVERAGE: "no_registry_coverage",
  INSUFFICIENT_PLATE: "insufficient_plate",
  UNREADABLE_PLATE: "unreadable_plate",
};

export const outcomeTotals = (details: CaseDetail[]) => OUTCOME_ORDER.map((outcome) => ({
  outcome,
  value: details.reduce((total, item) => total + (item.summary?.[SUMMARY_KEY[outcome]] ?? 0), 0),
}));

const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

/** Audit events per local calendar day, oldest first. */
export function activityByDay(details: CaseDetail[], days = 14) {
  const counts = new Map<string, number>();
  details.flatMap((item) => item.audit ?? []).forEach((entry) => {
    const key = dayKey(new Date(entry.created_at));
    counts.set(key, (counts.get(key) ?? 0) + 1);
  });
  const today = new Date();
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1 - index));
    return { date, value: counts.get(dayKey(date)) ?? 0 };
  });
}

export interface CoverageWarning {
  key: string;
  caseId: string;
  caseTitle: string;
  message: string;
  kind: "none" | "hint";
}

export function coverageWarnings(details: CaseDetail[]): CoverageWarning[] {
  return details.flatMap((item) => {
    const source = item.summary?.coverage ?? item.preflight?.coverage ?? [];
    const gaps = source.filter((row) => row.status === "no_coverage").map((row): CoverageWarning => ({
      key: `${item.id}-${row.clip_id}`, caseId: item.id, caseTitle: item.title, kind: "none",
      message: `${row.camera_label} uses ${row.format_label}: 0 of ${row.total_records.toLocaleString()} registry records are compatible.`,
    }));
    const hints = (item.summary?.format_hints ?? []).map((hint): CoverageWarning => ({
      key: `${item.id}-${hint.clip_id}-${hint.family}`, caseId: item.id, caseTitle: item.title, kind: "hint",
      message: `${hint.camera_label}: ${hint.reads} of ${hint.complete_reads} complete reads look ${hint.family_label}, and the registry has none.`,
    }));
    return [...gaps, ...hints];
  });
}

const ACTIONS: Record<string, string> = {
  CASE_CREATED: "Investigation created",
  EVIDENCE_INGESTED: "Evidence ingested",
  EVIDENCE_VERIFIED: "Evidence hashes verified",
  ANALYSIS_COMPLETED: "Analysis completed",
  ANALYSIS_FAILED: "Analysis failed",
  ANALYSIS_CANCELLED: "Analysis cancelled",
  NO_COVERAGE_ACKNOWLEDGED: "Coverage gap acknowledged",
  REGISTRY_RESCORED: "Re-matched with registry",
  INVESTIGATOR_OVERRIDE: "Investigator override",
  OVERRIDE_RESET: "Investigator override reset",
  LINK_REVIEWED: "Cross-camera link reviewed",
  CLIP_METADATA_UPDATED: "Clip details updated",
};

export const actionLabel = (action: string) => ACTIONS[action] ?? action.replaceAll("_", " ").toLowerCase();

export function recentActivity(details: CaseDetail[], limit = 8): (AuditEntry & { caseId: string; caseTitle: string })[] {
  return details
    .flatMap((item) => (item.audit ?? []).map((entry) => ({ ...entry, caseId: item.id, caseTitle: item.title })))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, limit);
}

export type GuideAction = { kind: "new" | "case" | "trace" | "registry"; caseId?: string; label: string };

export interface Insight {
  key: string;
  lead: string;
  text: string;
  help: string;
  tone: "warn" | "info";
  action: GuideAction;
}

const plural = (count: number, word: string, many = `${word}s`) => `${count.toLocaleString()} ${count === 1 ? word : many}`;
const topCase = (details: CaseDetail[], pick: (item: CaseDetail) => number) =>
  [...details].sort((a, b) => pick(b) - pick(a)).find((item) => pick(item) > 0);

/** Plain-language findings. Each one is computed from current case data and links to where it is resolved. */
export function insights(details: CaseDetail[], registry?: { total: number; synthetic: number } | null): Insight[] {
  const data = workload(details);
  const list: Insight[] = [];
  const unfinished = details.filter((item) => !isActiveRun(item) && (item.status === "FAILED" || item.status === "CANCELLED"));
  if (unfinished.length) list.push({ key: "unfinished", lead: plural(unfinished.length, "analysis", "analyses"), text: "did not finish.", help: "A run failed or was cancelled. Its partial results were discarded and your evidence is unchanged. Open the case and choose Retry.", tone: "warn", action: { kind: "case", caseId: unfinished[0].id, label: "Open case" } });
  if (data.possibleLinks) list.push({ key: "links", lead: plural(data.possibleLinks, "cross-camera link"), text: `${data.possibleLinks === 1 ? "needs" : "need"} your decision.`, help: "VITRA thinks the same vehicle may appear on two cameras. A link only counts after a person confirms it.", tone: "warn", action: { kind: "trace", caseId: topCase(details, (item) => item.summary?.possible_links ?? 0)?.id, label: "Review links" } });
  if (data.notSearched) list.push({ key: "coverage", lead: plural(data.notSearched, "readable plate"), text: `${data.notSearched === 1 ? "was" : "were"} not searched because the registry has no matching plate format.`, help: "This is not a no-match. The plate was read, but the registry holds no records in that format. Upload a compatible registry, then use Re-match.", tone: "warn", action: { kind: "registry", label: "Fix coverage" } });
  if (data.tracksReview) list.push({ key: "review", lead: plural(data.tracksReview, "track"), text: `${data.tracksReview === 1 ? "was" : "were"} flagged for a closer look.`, help: "These tracks are short, heavily covered, clipped by the frame or share a plate with another track. They are kept, but check them before relying on them.", tone: "warn", action: { kind: "case", caseId: topCase(details, (item) => item.summary?.tracks_review ?? 0)?.id, label: "Inspect tracks" } });
  const hints = details.flatMap((item) => (item.summary?.format_hints ?? []).map(() => item));
  if (hints.length) list.push({ key: "format", lead: plural(hints.length, "camera"), text: "may be set to the wrong plate format.", help: "Most complete reads look like a format the registry does not contain. Check the camera's plate format, then use Re-match.", tone: "warn", action: { kind: "case", caseId: hints[0].id, label: "Check format" } });
  const missing = (item: CaseDetail) => (item.clips ?? []).filter((clip) => !clip.recorded_at).length;
  const missingTotal = details.reduce((total, item) => total + missing(item), 0);
  if (missingTotal) list.push({ key: "time", lead: plural(missingTotal, "clip"), text: `${missingTotal === 1 ? "has" : "have"} no capture time, so time checks are off.`, help: "Without a capture time, VITRA cannot test whether a vehicle could really travel between two cameras. Add the time on the clip card.", tone: "warn", action: { kind: "case", caseId: topCase(details, missing)?.id, label: "Add time" } });
  const stale = details.filter((item) => item.stale);
  if (stale.length) list.push({ key: "stale", lead: plural(stale.length, "case"), text: `${stale.length === 1 ? "uses" : "use"} an older analysis version.`, help: "Results were re-scored, but a re-run applies the newest tracking and plate reading.", tone: "info", action: { kind: "case", caseId: stale[0].id, label: "Open case" } });
  if (registry?.total && registry.synthetic === registry.total) list.push({ key: "synthetic", lead: `All ${registry.total.toLocaleString()} registry records`, text: "are synthetic test data.", help: "The people and plates in this registry are fictional. A match against it is a demo result, not a real identification.", tone: "info", action: { kind: "registry", label: "View registry" } });
  return list;
}

export function nextStep(details: CaseDetail[]): { title: string; body: string; action: GuideAction } {
  if (!details.length) return { title: "Create your first investigation", body: "An investigation holds the CCTV clips and findings for one incident.", action: { kind: "new", label: "New investigation" } };
  const running = details.find(isActiveRun);
  if (running) return { title: `"${running.title}" is being analysed`, body: "You can follow its progress and see tracks as they finish.", action: { kind: "case", caseId: running.id, label: "Watch progress" } };
  const empty = details.find((item) => item.clip_count === 0);
  const waiting = details.find((item) => item.clip_count > 0 && !item.has_completed_run);
  if (waiting) return { title: `Run analysis on "${waiting.title}"`, body: "Its clips are ingested and ready to be analysed.", action: { kind: "case", caseId: waiting.id, label: "Open case" } };
  const linked = topCase(details, (item) => item.summary?.possible_links ?? 0);
  if (linked) return { title: `Review possible links in "${linked.title}"`, body: "Decide whether the same vehicle really appears on both cameras.", action: { kind: "trace", caseId: linked.id, label: "Review links" } };
  const gap = details.find((item) => item.summary?.no_registry_coverage);
  if (gap) return { title: "Add a compatible registry", body: `Readable plates in "${gap.title}" could not be searched because the registry has no records in their format.`, action: { kind: "registry", label: "Open registry" } };
  const flagged = topCase(details, (item) => item.summary?.tracks_review ?? 0);
  if (flagged) return { title: `Check flagged tracks in "${flagged.title}"`, body: "These tracks need a person to confirm they are reliable.", action: { kind: "case", caseId: flagged.id, label: "Inspect tracks" } };
  if (empty) return { title: `Add clips to "${empty.title}"`, body: "Upload CCTV footage to begin analysis.", action: { kind: "case", caseId: empty.id, label: "Add clips" } };
  return { title: "You are up to date", body: "Nothing needs a decision right now. Start a new investigation when you have footage.", action: { kind: "new", label: "New investigation" } };
}
