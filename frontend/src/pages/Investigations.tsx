import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { InvestigationTable } from "../components/InvestigationTable";
import { Empty, Loading, Notice, PageHeader } from "../components/ui";
import { isActiveRun, lastActivity, reviewState } from "../lib/overview";
import type { Overview } from "../lib/useOverview";
import type { CaseDetail } from "../types";

const FILTERS: { id: string; label: string; test: (item: CaseDetail) => boolean }[] = [
  { id: "all", label: "All", test: () => true },
  { id: "running", label: "Running", test: isActiveRun },
  { id: "waiting", label: "Awaiting analysis", test: (item) => !isActiveRun(item) && !item.has_completed_run },
  { id: "review", label: "To review", test: (item) => reviewState(item).tone === "amber" },
  { id: "coverage", label: "Coverage gap", test: (item) => item.summary?.coverage_status !== "covered" && Boolean(item.summary?.coverage?.length) },
];

export default function Investigations({ overview, ready, onNewCase }: {
  overview: Overview;
  ready: boolean;
  onNewCase: () => void;
  onOpenCase: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((item) => [item.id, overview.details.filter(item.test).length])), [overview.details]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rule = FILTERS.find((item) => item.id === filter) ?? FILTERS[0];
    return overview.details
      .filter((item) => rule.test(item) && (!needle || item.title.toLowerCase().includes(needle)
        || (item.clips ?? []).some((clip) => clip.camera_label.toLowerCase().includes(needle) || clip.filename.toLowerCase().includes(needle))))
      .sort((a, b) => new Date(lastActivity(b)).getTime() - new Date(lastActivity(a)).getTime());
  }, [overview.details, query, filter]);

  return (
    <>
      <PageHeader title="Investigations" description="Every case, its analysis state and what still needs review."
        actions={<button className="btn btn-primary" onClick={onNewCase}><Plus size={15} /> New investigation</button>} />
      {overview.failed.length > 0 && <Notice tone="crimson" live="alert" title="Some investigations could not be loaded">{overview.failed.join(", ")}</Notice>}
      <section className="panel" aria-label="Investigation list">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-2">
          <label className="relative min-w-[200px] flex-1">
            <Search size={15} aria-hidden="true" className="absolute left-2 top-2 text-muted" />
            <input aria-label="Search investigations" className="field pl-7" placeholder="Search case, camera or file" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filter investigations">
            {FILTERS.map((item) => (
              <button key={item.id} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)} className={`btn ${filter === item.id ? "border-accent-soft bg-accent-tint text-accent-soft hover:bg-accent-tint" : ""}`}>
                {item.label} <span className="num">{counts[item.id] ?? 0}</span>
              </button>
            ))}
          </div>
        </div>
        {!ready || (overview.loading && !overview.details.length && !overview.failed.length) ? <Loading>Loading investigations…</Loading>
          : visible.length ? <InvestigationTable items={visible} />
            : overview.details.length ? <Empty title="No investigations match">Clear the search or choose another filter.</Empty>
              : <Empty title="No investigations yet"><button className="btn btn-primary mt-2" onClick={onNewCase}><Plus size={15} /> New investigation</button></Empty>}
      </section>
    </>
  );
}
