import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { Candidate, MatchResult, SlotDiff } from "../types";
import { Badge, RegistryStatus, ScoreBar, percent, pretty } from "./ui";

const diffStyle: Record<SlotDiff["kind"], string> = {
  exact: "bg-emerald-100 text-emerald-900",
  confusable: "bg-amber-100 text-amber-900",
  mismatch: "bg-rose-100 text-rose-900",
  hard_mismatch: "bg-rose-200 text-rose-950",
  unknown: "slot-hatched",
  unobserved: "slot-hatched",
};

export function PlateDiff({ diff }: { diff: SlotDiff[] }) {
  return (
    <span className="inline-flex font-mono text-xs font-semibold">
      {diff.map((slot) => (
        <span
          key={slot.position}
          title={`Slot ${slot.position + 1}: read ${slot.query}, registry ${slot.registry} (${pretty(slot.kind)})`}
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
            <span className={`num text-sm font-semibold ${rejected ? "text-muted" : ""}`}>{percent(candidate.confidence)}</span>
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-muted">
            <span>{vehicle.colour} {vehicle.make} {vehicle.model} · {pretty(vehicle.body_type)}</span>
            <RegistryStatus status={vehicle.status} />
            {candidate.vetoed && <Badge tone="crimson">Vetoed</Badge>}
          </span>
        </span>
        {expanded ? <ChevronDown size={16} className="mt-1 text-muted" /> : <ChevronRight size={16} className="mt-1 text-muted" />}
      </button>
      {expanded && (
        <div className="space-y-2 px-3 pb-3 pl-9">
          <div className="space-y-1">
            <ScoreBar label="Plate" value={sub.plate} weight={weights.plate} />
            <ScoreBar label="Body type" value={sub.body_type} weight={weights.body_type} />
            <ScoreBar label="Colour" value={sub.colour} weight={weights.colour} />
            <ScoreBar label="Make/model" value={sub.make_model} weight={weights.make_model} />
          </div>
          <ul className="list-disc space-y-0.5 pl-4 text-2xs text-muted">
            {candidate.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          {vehicle.owner_name && (
            <div className="text-2xs text-muted">Registered: {vehicle.owner_name}, {vehicle.owner_city} · {vehicle.year}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function Shortlist({ result }: { result: MatchResult }) {
  const confident = result.status === "CONFIDENT_SHORTLIST";
  return (
    <div>
      <div className={`border-b px-3 py-2 ${confident ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50"}`}>
        <div className={`text-xs font-semibold ${confident ? "text-emerald-900" : "text-rose-900"}`}>
          {confident ? "Confident shortlist" : "No confident match"}
        </div>
        <ul className={`mt-0.5 text-2xs ${confident ? "text-emerald-800" : "text-rose-800"}`}>
          {result.diagnostics.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
      <div className="flex justify-between border-b border-line px-3 py-1 text-2xs text-muted">
        <span>{pretty(result.regime)} · {result.known_chars} known chars</span>
        <span className="num">{result.registry_size} vehicles · {result.elapsed_ms.toFixed(1)} ms</span>
      </div>
      {result.candidates.map((candidate, index) => (
        <CandidateRow key={candidate.vehicle.plate} candidate={candidate} open={index === 0} />
      ))}
      {result.rejected_candidates.length > 0 && (
        <>
          <div className="border-y border-line bg-canvas px-3 py-1 text-2xs font-semibold text-muted">
            Closest rejected candidates, not identifications
          </div>
          {result.rejected_candidates.map((candidate) => (
            <CandidateRow key={candidate.vehicle.plate} candidate={candidate} open={false} rejected />
          ))}
        </>
      )}
    </div>
  );
}
