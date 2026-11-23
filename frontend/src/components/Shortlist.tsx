import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { Candidate, MatchResult, SlotDiff } from "../types";
import { Badge, OUTCOMES, RegistryStatus, ScoreBar, pretty, score } from "./ui";

const diffStyle: Record<SlotDiff["kind"], string> = {
  exact: "bg-emerald-100 text-emerald-900",
  confusable: "bg-amber-100 text-amber-900",
  mismatch: "bg-rose-100 text-rose-900",
  hard_mismatch: "bg-rose-200 text-rose-950",
  unknown: "slot-hatched",
  unobserved: "slot-hatched",
};

const kindLabel: Record<SlotDiff["kind"], string> = {
  exact: "exact match",
  confusable: "OCR-confusable",
  mismatch: "low-confidence disagreement",
  hard_mismatch: "high-confidence contradiction",
  unknown: "unreadable",
  unobserved: "not visible",
};

const banner = {
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  crimson: "border-rose-200 bg-rose-50 text-rose-900",
  navy: "border-navy/20 bg-navy-tint text-navy",
  slate: "border-line bg-canvas text-ink",
};

export function PlateDiff({ diff }: { diff: SlotDiff[] }) {
  return (
    <span className="inline-flex font-mono text-xs font-semibold">
      {diff.map((slot) => (
        <span
          key={slot.position}
          title={`Slot ${slot.position + 1}: read ${slot.query}, registry ${slot.registry} (${kindLabel[slot.kind]})`}
          className={`-ml-px flex h-6 w-[18px] items-center justify-center border border-slate-300 first:ml-0 ${diffStyle[slot.kind]}`}
        >
          {slot.registry}
        </span>
      ))}
    </span>
  );
}

function CandidateRow({ candidate, open, rejected }: { candidate: Candidate; open: boolean; rejected?: boolean }) {
  const [expanded, setExpanded] = useState(open);
  const { vehicle, sub_scores: sub, weights } = candidate;
  return (
    <div className="border-b border-line last:border-b-0">
      <button className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-canvas" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <span className="num mt-1 w-4 text-2xs text-muted">{candidate.rank}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <PlateDiff diff={candidate.slot_diff} />
            <span className={`num text-sm font-semibold ${rejected ? "text-muted" : ""}`} title="Uncalibrated match score, not a probability">{score(candidate.score)}</span>
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-muted">
            <span>{vehicle.colour} {vehicle.make} {vehicle.model} · {pretty(vehicle.body_type)}</span>
            {!rejected && <RegistryStatus status={vehicle.status} />}
            {candidate.vetoed && <Badge tone="crimson">Body conflict</Badge>}
          </span>
        </span>
        {expanded ? <ChevronDown size={16} className="mt-1 shrink-0 text-muted" /> : <ChevronRight size={16} className="mt-1 shrink-0 text-muted" />}
      </button>
      {expanded && (
        <div className="space-y-2 px-3 pb-3 pl-9">
          <div className="space-y-1">
            <ScoreBar label="Plate" value={sub.plate} weight={weights.plate} />
            <div className="pt-0.5 text-2xs font-medium text-muted">Supporting attributes only</div>
            <ScoreBar label="Body type" value={sub.body_type} weight={weights.body_type} />
            <ScoreBar label="Colour" value={sub.colour} weight={weights.colour} />
            <ScoreBar label="Make/model" value={sub.make_model} weight={weights.make_model} />
          </div>
          {candidate.blocking_reasons.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-2xs text-rose-800">
              {candidate.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          )}
          <ul className="list-disc space-y-0.5 pl-4 text-2xs text-muted">
            {candidate.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          {!rejected && vehicle.owner_name && (
            <div className="text-2xs text-muted">Registered: {vehicle.owner_name}, {vehicle.owner_city} · {vehicle.year}{vehicle.source === "synthetic" ? " · synthetic record" : ""}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function Shortlist({ result }: { result: MatchResult }) {
  const info = OUTCOMES[result.outcome];
  const suggestions = result.attribute_suggestions;
  const t = result.thresholds;
  return (
    <div>
      <div className={`border-b px-3 py-2 ${banner[info.tone]}`}>
        <div className="text-xs font-semibold">{result.status === "CONFIDENT_SHORTLIST" ? info.label : `No confident match · ${info.label}`}</div>
        <ul className="mt-0.5 space-y-0.5 text-2xs">
          {result.diagnostics.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
      <div className="flex flex-wrap justify-between gap-x-3 border-b border-line px-3 py-1 text-2xs text-muted">
        <span>{result.known_chars} readable plate character{result.known_chars === 1 ? "" : "s"}</span>
        <span className="num">{result.registry_size.toLocaleString()} vehicles · {result.elapsed_ms.toFixed(1)} ms</span>
      </div>
      {result.candidates.length > 0 && (
        <div className="border-b border-line bg-canvas px-3 py-1 text-2xs text-muted">Ordered by plate evidence. Scores are uncalibrated, not probabilities.</div>
      )}
      {result.candidates.map((candidate, index) => (
        <CandidateRow key={candidate.vehicle.plate} candidate={candidate} open={index === 0} />
      ))}
      {result.rejected_candidates.length > 0 && (
        <>
          <div className="border-y border-line bg-canvas px-3 py-1 text-2xs font-semibold text-muted">
            {result.outcome === "AMBIGUOUS" ? "Plates that remain possible, not identifications" : "Closest registry plates by plate evidence, not identifications"}
          </div>
          {result.rejected_candidates.map((candidate) => (
            <CandidateRow key={candidate.vehicle.plate} candidate={candidate} open={false} rejected />
          ))}
        </>
      )}
      {suggestions.vehicles.length > 0 && (
        <details className="border-t border-line">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Similar-looking vehicles <span className="num font-normal text-muted">{suggestions.similar_count.toLocaleString()}</span></summary>
          <div className="px-3 pb-2 text-2xs text-muted">
            <p className="mb-1">Unranked examples with {suggestions.basis.join(" and ")}. These are not identifications.</p>
            <ul className="divide-y divide-line border border-line">
              {suggestions.vehicles.map((vehicle) => (
                <li key={vehicle.plate} className="flex flex-wrap justify-between gap-2 px-2 py-1">
                  <span className="num">{vehicle.plate}</span>
                  <span>{vehicle.colour} {vehicle.make} {vehicle.model}</span>
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}
      {t && Object.keys(t).length > 0 && (
        <details className="border-t border-line">
          <summary className="cursor-pointer px-3 py-2 text-2xs font-medium text-muted">Decision thresholds</summary>
          <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 px-3 pb-2 text-2xs text-muted">
            <dt>Readable characters</dt><dd className="num">≥ {t.min_readable_chars}</dd>
            <dt>Characters agreeing with plate</dt><dd className="num">≥ {t.min_supporting_chars}</dd>
            <dt>Exact characters</dt><dd className="num">≥ {t.min_exact_chars}</dd>
            <dt>Plate agreement</dt><dd className="num">≥ {t.min_plate_agreement}</dd>
            <dt>High-confidence contradictions</dt><dd className="num">≤ {t.max_hard_contradictions}</dd>
            <dt>Match score</dt><dd className="num">≥ {t.min_match_score}</dd>
            <dt>Score gap to next vehicle</dt><dd className="num">≥ {t.min_score_gap}</dd>
          </dl>
        </details>
      )}
    </div>
  );
}
