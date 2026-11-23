import { analysisState, lastActivity, reviewState } from "../lib/overview";
import type { CaseDetail } from "../types";
import { InfoTip } from "./InfoTip";
import { Badge, relativeTime, type Tone } from "./ui";

function registryState(item: CaseDetail): { label: string; tone: Tone; title: string } {
  if ((item.summary?.format_hints?.length ?? 0) > 0) return { label: "Possible format gap", tone: "amber", title: "Most complete reads look like a plate format the registry does not contain" };
  if (item.summary?.coverage_status === "none") return { label: "No coverage", tone: "amber", title: "No clip's plate format has compatible registry records" };
  if (item.summary?.coverage_status === "partial") return { label: "Partial coverage", tone: "amber", title: "At least one clip's plate format has no compatible registry records" };
  return item.clip_count ? { label: "Covered", tone: "emerald", title: "Compatible registry records exist for every clip" } : { label: "No clips", tone: "slate", title: "Add a clip to check registry coverage" };
}

function PlateBar({ item }: { item: CaseDetail }) {
  const summary = item.summary;
  const total = summary?.tracks ?? 0;
  if (!total) return <span className="text-2xs text-muted">No tracks yet</span>;
  const parts = [
    { value: summary.readable_plates, className: "bg-[#9C8CFF]" },
    { value: summary.partial_plates, className: "bg-signal" },
    { value: summary.no_plate_chars, className: "bg-slate-400" },
  ];
  return (
    <span className="block w-full min-w-[120px]" title={`${summary.readable_plates} readable, ${summary.partial_plates} partial, ${summary.no_plate_chars} unreadable`}>
      <span className="flex h-1.5 gap-px overflow-hidden rounded-full" aria-hidden="true">
        {parts.map((part, index) => part.value > 0 && <span key={index} className={part.className} style={{ width: `${(part.value / total) * 100}%` }} />)}
      </span>
      <span className="num mt-1 block whitespace-nowrap text-2xs text-muted"><span className="text-ink">{summary.readable_plates}</span> full · {summary.partial_plates} partial · {summary.no_plate_chars} none</span>
    </span>
  );
}

const Demo = ({ item }: { item: CaseDetail }) => (item.clips ?? []).some((clip) => clip.synthetic)
  ? <Badge tone="slate" title="Clips are labelled synthetic test fixtures">Demo evidence</Badge> : null;

export function InvestigationTable({ items }: { items: CaseDetail[] }) {
  return (
    <>
      <ul className="divide-y divide-line lg:hidden">
        {items.map((item) => {
          const analysis = analysisState(item);
          const review = reviewState(item);
          const registry = registryState(item);
          const time = lastActivity(item);
          return (
            <li key={item.id} className="space-y-1.5 px-3 py-3">
              <div className="flex flex-wrap items-center gap-1.5"><a href={`#/${item.id}/case`} className="break-words text-[13px] font-semibold text-accent-soft underline-offset-2 hover:underline">{item.title}</a><Demo item={item} /></div>
              <PlateBar item={item} />
              <div className="flex flex-wrap items-center gap-1"><Badge tone={analysis.tone}>{analysis.label}</Badge><Badge tone={review.tone}>{review.label}</Badge><Badge tone={registry.tone} title={registry.title}>{registry.label}</Badge></div>
              <div className="num text-2xs text-muted" title={time ? new Date(time).toLocaleString() : undefined}>{item.clip_count} clip{item.clip_count === 1 ? "" : "s"} · {item.summary?.tracks ?? 0} tracks · {relativeTime(time)}</div>
            </li>
          );
        })}
      </ul>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full border-collapse text-xs">
          <caption className="sr-only">Investigations with clips, tracks, plate reads, registry coverage, analysis state, review status and last activity</caption>
          <thead>
            <tr>
              <th scope="col" className="th !px-3">Investigation</th>
              <th scope="col" className="th text-right">Clips</th>
              <th scope="col" className="th text-right">Tracks</th>
              <th scope="col" className="th">Plate reads <InfoTip label="plate reads">Full plates have 5 or more readable characters. Partial plates have 1 to 4. None means no character could be read.</InfoTip></th>
              <th scope="col" className="th">Registry <InfoTip label="registry coverage">Covered means the registry holds records in this camera's plate format, so plates can really be searched.</InfoTip></th>
              <th scope="col" className="th">Analysis</th>
              <th scope="col" className="th">Review</th>
              <th scope="col" className="th">Last activity</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const analysis = analysisState(item);
              const review = reviewState(item);
              const registry = registryState(item);
              const time = lastActivity(item);
              return (
                <tr key={item.id} className="hover:bg-raised">
                  <td className="td min-w-[210px] !px-3 !py-2.5">
                    <a href={`#/${item.id}/case`} className="font-semibold text-white underline-offset-2 hover:text-accent-soft hover:underline">{item.title}</a>
                    <span className="mt-1 flex flex-wrap gap-1 empty:hidden"><Demo item={item} /></span>
                  </td>
                  <td className="td num text-right">{item.clip_count}</td>
                  <td className="td num text-right">{item.summary?.tracks ?? 0}</td>
                  <td className="td"><PlateBar item={item} /></td>
                  <td className="td"><Badge tone={registry.tone} title={registry.title}>{registry.label}</Badge></td>
                  <td className="td"><Badge tone={analysis.tone}>{analysis.label}</Badge></td>
                  <td className="td"><Badge tone={review.tone}>{review.label}</Badge></td>
                  <td className="td num whitespace-nowrap text-2xs text-muted" title={time ? new Date(time).toLocaleString() : undefined}>{relativeTime(time)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
