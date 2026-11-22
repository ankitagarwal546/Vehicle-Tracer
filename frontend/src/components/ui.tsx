import type { ReactNode } from "react";
import type { MatchStatus } from "../types";

type Tone = "emerald" | "amber" | "crimson" | "slate" | "navy";

const tones: Record<Tone, string> = {
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-800",
  amber: "border-amber-300 bg-amber-50 text-amber-800",
  crimson: "border-rose-300 bg-rose-50 text-rose-800",
  slate: "border-line bg-canvas text-muted",
  navy: "border-navy/30 bg-navy-tint text-navy",
};

export function Badge({ tone = "slate", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap border px-1.5 py-px text-2xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function VerdictBadge({ status }: { status: MatchStatus | null }) {
  if (status === "CONFIDENT_SHORTLIST") return <Badge tone="emerald">Shortlist</Badge>;
  if (status === "NO_CONFIDENT_MATCH") return <Badge tone="crimson">No confident match</Badge>;
  return <Badge>Pending</Badge>;
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
    <span className="inline-flex font-mono font-semibold" aria-label={`Plate ${text.replaceAll("?", " unknown ")}`}>
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
      <span className="num text-right text-muted">{weight !== undefined ? `×${weight.toFixed(2)}` : ""}</span>
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

export const percent = (value: number | null | undefined) => (value == null ? "n/a" : `${value.toFixed(1)}%`);
export const seconds = (value: number) => `${value.toFixed(2)}s`;
export const shortHash = (hash: string) => `${hash.slice(0, 10)}…${hash.slice(-6)}`;
export const pretty = (value: string) => value.replaceAll("_", " ");
