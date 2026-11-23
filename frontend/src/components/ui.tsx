import type { ReactNode } from "react";
import type { Outcome, ReviewStatus } from "../types";

export type Tone = "emerald" | "amber" | "crimson" | "slate" | "navy";

const tones: Record<Tone, string> = {
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-800",
  amber: "border-amber-300 bg-amber-50 text-amber-800",
  crimson: "border-rose-300 bg-rose-50 text-rose-800",
  slate: "border-line bg-canvas text-muted",
  navy: "border-navy/30 bg-navy-tint text-navy",
};

export const OUTCOMES: Record<Outcome, { label: string; short: string; tone: Tone; help: string }> = {
  PLATE_CANDIDATE: { label: "Plate-supported candidate", short: "Candidate", tone: "emerald", help: "Readable plate cleared every matching gate." },
  AMBIGUOUS: { label: "Ambiguous candidates", short: "Ambiguous", tone: "amber", help: "Several registry plates fit the readable characters." },
  NO_REGISTRY_MATCH: { label: "No registry match", short: "No match", tone: "crimson", help: "Plate is readable but no registry vehicle agrees with it." },
  INSUFFICIENT_PLATE: { label: "Partial plate only", short: "Partial plate", tone: "navy", help: "Too few readable characters to shortlist a vehicle." },
  UNREADABLE_PLATE: { label: "Plate unreadable", short: "Unreadable", tone: "slate", help: "No plate character could be read." },
};

export const OUTCOME_ORDER: Outcome[] = ["PLATE_CANDIDATE", "AMBIGUOUS", "NO_REGISTRY_MATCH", "INSUFFICIENT_PLATE", "UNREADABLE_PLATE"];

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap border px-1.5 py-px text-2xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function OutcomeBadge({ outcome, long = false }: { outcome: Outcome | null; long?: boolean }) {
  if (!outcome) return <Badge>Pending</Badge>;
  const item = OUTCOMES[outcome];
  return <Badge tone={item.tone} title={item.help}>{long ? item.label : item.short}</Badge>;
}

export function LinkBadge({ status }: { status: ReviewStatus | null }) {
  if (status === "confirmed") return <Badge tone="emerald">Confirmed link</Badge>;
  if (status === "proposed") return <Badge tone="amber">Possible link</Badge>;
  if (status === "rejected") return <Badge>Link rejected</Badge>;
  return null;
}

export function RegistryStatus({ status }: { status: string }) {
  if (status === "STOLEN_ALERT") return <Badge tone="crimson">Stolen alert</Badge>;
  if (status === "EXPIRED") return <Badge tone="amber">Expired</Badge>;
  return <Badge>Active</Badge>;
}

export function PlateText({ text, size = "md" }: { text: string; size?: "sm" | "md" | "lg" }) {
  const cell = { sm: "h-5 w-3.5 text-2xs", md: "h-6 w-[18px] text-xs", lg: "h-8 w-6 text-base" }[size];
  if (!text) return <span className="text-2xs text-muted">Plate not read</span>;
  return (
    <span className="inline-flex max-w-full flex-wrap font-mono font-semibold" aria-label={`Plate ${text.replaceAll("?", " unknown ")}`}>
      {[...text].map((char, index) => (
        <span
          key={index}
          className={`-ml-px flex items-center justify-center border border-slate-300 first:ml-0 ${cell} ${char === "?" ? "slot-hatched" : "bg-white"}`}
        >
          {char}
        </span>
      ))}
    </span>
  );
}

export function ScoreBar({ label, value, weight }: { label: string; value: number | null; weight?: number }) {
  return (
    <div className="grid grid-cols-[76px_1fr_38px_38px] items-center gap-2 text-2xs">
      <span className="text-muted">{label}</span>
      <span className="h-1.5 bg-slate-100">
        {value !== null && <span className="block h-full bg-navy" style={{ width: `${Math.max(0, Math.min(value, 1)) * 100}%` }} />}
      </span>
      <span className="num text-right">{value === null ? "n/a" : value.toFixed(2)}</span>
      <span className="num text-right text-muted">{weight ? `×${weight.toFixed(2)}` : ""}</span>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-4 py-8 text-center">
      <div className="text-xs font-semibold">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

export function Pagination({ page, pages, total, label, onChange }: {
  page: number;
  pages: number;
  total: number;
  label: string;
  onChange: (page: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
      <span className="num text-2xs text-muted">{total} {label} · page {page} of {pages}</span>
      <span className="flex gap-1">
        <button className="btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
        <button className="btn" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button>
      </span>
    </div>
  );
}

export const score = (value: number | null | undefined) => (value == null ? "n/a" : value.toFixed(1));
export const seconds = (value: number) => `${value.toFixed(2)}s`;
export const shortHash = (hash: string) => `${hash.slice(0, 10)}…${hash.slice(-6)}`;
export const pretty = (value: string) => value.replaceAll("_", " ");
export const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** Format a stored UTC instant for a datetime-local input in the camera's own timezone. */
export const toZoneInput = (iso: string | null, zone: string | null) => {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat("sv-SE", {
      timeZone: zone || browserZone(), year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).format(new Date(iso)).replace(" ", "T");
  } catch {
    return iso.slice(0, 16);
  }
};

export const formatInZone = (iso: string, zone?: string | null) => {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: zone || undefined, dateStyle: "medium", timeStyle: "short",
    }).format(new Date(iso)) + (zone ? ` ${zone}` : "");
  } catch {
    return new Date(iso).toLocaleString();
  }
};
