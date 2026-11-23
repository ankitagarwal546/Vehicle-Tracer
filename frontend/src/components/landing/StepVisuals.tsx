import { AlertTriangle, CheckCircle2, CircleHelp, Database, FileCheck2, Fingerprint, Link2, ListChecks, ScanLine } from "lucide-react";
import { OpeningScene } from "../OpeningScene";

const stagger = (active: boolean, index: number, step = 90) => ({
  opacity: active ? 1 : 0,
  transform: active ? "none" : "translateY(10px)",
  transition: "opacity 520ms ease, transform 520ms cubic-bezier(0.16, 1, 0.3, 1)",
  transitionDelay: active ? `${index * step}ms` : "0ms",
});

export function DemoTag() {
  return <span className="rounded border border-white/20 bg-black/30 px-1.5 py-px text-[10px] font-medium text-[#CFCAE6]">Demo data</span>;
}

const CLIPS = [
  ["North gate", "1920×1080", "02:14", "9f3c…a71e", "Verified"],
  ["Ring road", "3840×2160", "01:00", "24b7…c58d", "Verified"],
  ["Toll plaza", "1280×720", "04:32", "e10a…77f2", "Verified"],
  ["Depot exit", "1920×1080", "00:48", "6cd2…03ba", "No capture time"],
  ["Car park", "960×540", "03:05", "b84e…1d90", "Verified"],
];

export function IngestVisual({ active }: { active: boolean }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-white/10 bg-[#120E24]">
      <table className="w-full min-w-[430px] text-left text-[11px]">
        <thead className="bg-white/[0.04] text-[#CFCAE6]"><tr>{["Camera", "Resolution", "Length", "SHA-256", "Custody"].map((head) => <th key={head} scope="col" className="px-3 py-2 font-semibold">{head}</th>)}</tr></thead>
        <tbody>
          {CLIPS.map((row, index) => (
            <tr key={row[0]} className="border-t border-white/[0.07]" style={stagger(active, index)}>
              <td className="px-3 py-2 font-medium text-white">{row[0]}</td>
              <td className="num px-3 py-2 text-[#CFCAE6]">{row[1]}</td>
              <td className="num px-3 py-2 text-[#CFCAE6]">{row[2]}</td>
              <td className="num px-3 py-2 text-[#CFCAE6]">{row[3]}</td>
              <td className="px-3 py-2"><span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${row[4] === "Verified" ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-amber-300 bg-amber-50 text-amber-800"}`}>{row[4]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DetectVisual({ animated }: { animated: boolean }) {
  return (
    <div className="relative h-60 overflow-hidden rounded-lg border border-white/10 bg-[#0D0F15] sm:h-72">
      <OpeningScene animated={animated} embedded />
      <div className="scene-lines absolute inset-0" />
      <span className="absolute left-2 top-2 rounded border border-white/20 bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">Illustrative scene</span>
    </div>
  );
}

const READS = [["F 018", "DE?O4??2"], ["F 031", "?EMO??72"], ["F 047", "D?M?4?7?"]];
const FUSED = "DEMO4?72";

export function RecoverVisual({ active }: { active: boolean }) {
  return (
    <div className="rounded-lg border border-white/10 bg-[#120E24] p-3">
      <div className="space-y-1">
        {READS.map(([label, text], rowIndex) => (
          <div key={label} className="grid grid-cols-[48px_repeat(8,minmax(0,1fr))] items-center gap-1" style={stagger(active, rowIndex, 160)}>
            <span className="num text-[10px] text-[#CFCAE6]">{label}</span>
            {[...text].map((char, index) => <span key={index} className={`num flex h-7 items-center justify-center rounded text-[11px] font-semibold ${char === "?" ? "bg-white/[0.04] text-[#8F89AD]" : "bg-white/[0.13] text-white"}`}>{char}</span>)}
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-[48px_repeat(8,minmax(0,1fr))] items-center gap-1 border-t border-white/10 pt-2">
        <span className="num text-[10px] font-semibold text-signal">FUSED</span>
        {[...FUSED].map((char, index) => (
          <span key={index} style={stagger(active, index + 5, 80)} className={`num flex h-9 items-center justify-center rounded text-sm font-semibold ${char === "?" ? "border border-dashed border-signal text-signal" : "bg-[#F4F1FF] text-[#14101F]"}`}>{char}</span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-[#CFCAE6]" style={stagger(active, 14, 80)}>No frame showed slot 6, so it stays <span className="num font-semibold text-signal">?</span>. VITRA never guesses it.</p>
    </div>
  );
}

const NODES = [
  { label: "Plate read", sub: "OCR evidence", x: 9, y: 45, icon: ScanLine, tone: "border-accent-soft/60 text-accent-soft" },
  { label: "Format check", sub: "Registry coverage", x: 32, y: 45, icon: ListChecks, tone: "border-amber-400 text-amber-800" },
  { label: "Registry", sub: "Compatible rows", x: 55, y: 45, icon: Database, tone: "border-emerald-300 text-emerald-800" },
  { label: "Candidate", sub: "Clears every gate", x: 89, y: 15, icon: CheckCircle2, tone: "border-emerald-300 text-emerald-800" },
  { label: "No confident match", sub: "Explained, not forced", x: 89, y: 47, icon: CircleHelp, tone: "border-rose-300 text-rose-800" },
  { label: "No coverage", sub: "Not a no-match", x: 32, y: 76, icon: AlertTriangle, tone: "border-amber-400 text-amber-800" },
];

export function MatchVisual({ active }: { active: boolean }) {
  return (
    <div className="relative h-64 overflow-hidden rounded-lg border border-white/10 bg-[#120E24] bg-[radial-gradient(rgb(255_255_255/0.07)_1px,transparent_1px)] [background-size:14px_14px]">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" className="absolute inset-0 h-full w-full">
        {["M9 45H55", "M55 45C68 45 66 15 89 15", "M55 45C68 45 70 47 89 47", "M32 45V76"].map((d) => (
          <path key={d} d={d} className={active ? "flow-edge" : ""} fill="none" stroke="#8D7CF2" strokeOpacity="0.75" strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      {NODES.map(({ label, sub, x, y, icon: Icon, tone }, index) => (
        <div key={label} className="absolute w-[54px] -translate-x-1/2 -translate-y-[14px] text-center sm:w-28" style={{ left: `${Math.min(Math.max(x, 12), 87)}%`, top: `${y}%` }}>
          <div style={stagger(active, index, 130)}>
            <span className={`mx-auto flex h-8 w-8 items-center justify-center rounded-lg border bg-[#1B1533] ${tone}`}><Icon size={15} aria-hidden="true" /></span>
            <span className="mt-1 block text-[10px] font-semibold leading-3 text-white">{label}</span>
            <span className="hidden text-[9px] leading-3 text-[#BDB7D6] sm:block">{sub}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

const REVIEW = [
  { icon: Link2, title: "Possible link", detail: "North gate to Ring road, 6 of 7 characters agree", tone: "border-amber-400 text-amber-800", offset: "ml-10 sm:ml-24" },
  { icon: Fingerprint, title: "Chain of custody", detail: "Clip hash matched before analysis", tone: "border-accent-soft/60 text-accent-soft", offset: "ml-5 sm:ml-12" },
  { icon: FileCheck2, title: "Investigator confirmed", detail: "Decision and report written to the audit log", tone: "border-emerald-300 text-emerald-800", offset: "ml-0" },
];

export function ReviewVisual({ active }: { active: boolean }) {
  return (
    <div className="space-y-[-6px] pb-1">
      {REVIEW.map(({ icon: Icon, title, detail, tone, offset }, index) => (
        <div key={title} className={`${offset} relative`} style={{ ...stagger(active, index, 220), zIndex: index }}>
          <div className="flex items-center gap-3 rounded-lg border border-white/15 bg-[#1B1533] px-3 py-2.5 shadow-lg shadow-black/40">
            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${tone}`}><Icon size={15} aria-hidden="true" /></span>
            <span className="min-w-0"><span className="block text-xs font-semibold text-white">{title}</span><span className="block truncate text-[11px] text-[#CFCAE6]">{detail}</span></span>
          </div>
        </div>
      ))}
    </div>
  );
}
