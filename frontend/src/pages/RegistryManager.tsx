import { FlaskConical, Search, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Empty, RegistryStatus, pretty } from "../components/ui";
import { BODY_TYPES, COLOURS, type MatchResult, type RegistryVehicle } from "../types";

const PAGE_SIZE = 25;

export default function RegistryManager({ onError, onRegistryChanged }: { onError: (message: string) => void; onRegistryChanged: () => void }) {
  const [rows, setRows] = useState<RegistryVehicle[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [body, setBody] = useState("");
  const [colour, setColour] = useState("");
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [notice, setNotice] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [plate, setPlate] = useState("MH12DE14?3");
  const [plateConf, setPlateConf] = useState(0.9);
  const [testColour, setTestColour] = useState("white");
  const [testBody, setTestBody] = useState("suv");
  const [result, setResult] = useState<MatchResult | null>(null);
  const [running, setRunning] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.registry({ q, status, body_type: body, colour, page, page_size: PAGE_SIZE });
      setRows(data.items);
      setTotal(data.total);
    } catch (error) {
      onError((error as Error).message);
    }
  }, [q, status, body, colour, page, onError]);

  useEffect(() => {
    const timer = setTimeout(load, 150);
    return () => clearTimeout(timer);
  }, [load]);

  const upload = async (selected: File | undefined) => {
    if (!selected) return;
    if (mode === "replace" && !window.confirm(`Replace the entire registry with ${selected.name}? Existing rows will be deleted.`)) return;
    try {
      const outcome = await api.uploadRegistry(selected, mode);
      setNotice(`${selected.name}: ${outcome.inserted} added, ${outcome.updated} updated, ${outcome.rejected} rejected. Registry now holds ${outcome.total}.`);
      setPage(1);
      await load();
      onRegistryChanged();
    } catch (error) {
      onError((error as Error).message);
    }
  };

  const runTest = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    try {
      setResult(await api.matchTest({ plate, plate_confidence: plateConf, colour: testColour || undefined, body_type: testBody || undefined, body_confidence: 0.8 }));
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const pages = Math.max(Math.ceil(total / PAGE_SIZE), 1);
  const filter = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(1); };

  return (
    <div className="relative grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
      <section className="panel min-w-0">
        <div className="panel-head flex-wrap">
          <span>Vehicle registry <span className="num font-normal text-muted">{total}</span></span>
          <span className="flex flex-wrap items-center gap-1.5">
            <select aria-label="Upload mode" className="field w-auto" value={mode} onChange={(e) => setMode(e.target.value as "merge" | "replace")}>
              <option value="merge">Merge</option><option value="replace">Replace all</option>
            </select>
            <button className="btn" onClick={() => file.current?.click()}><Upload size={16} /> Upload CSV/JSON</button>
            <input ref={file} type="file" accept=".csv,.json" className="hidden" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} />
            <button className="btn btn-primary" onClick={() => setDrawer(!drawer)} aria-expanded={drawer}><FlaskConical size={16} /> Matcher sandbox</button>
          </span>
        </div>
        {notice && <div className="border-b border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900">{notice}</div>}
        <div className="grid gap-2 border-b border-line p-2 sm:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr]">
          <label className="relative"><Search size={16} className="absolute left-2 top-1.5 text-muted" /><input aria-label="Search registry" className="field pl-7" placeholder="Search plate, make, model, owner" value={q} onChange={(e) => filter(setQ)(e.target.value)} /></label>
          <select aria-label="Filter status" className="field" value={status} onChange={(e) => filter(setStatus)(e.target.value)}><option value="">All statuses</option><option value="ACTIVE">Active</option><option value="STOLEN_ALERT">Stolen alert</option><option value="EXPIRED">Expired</option></select>
          <select aria-label="Filter body" className="field" value={body} onChange={(e) => filter(setBody)(e.target.value)}><option value="">All body types</option>{BODY_TYPES.map((v) => <option key={v} value={v}>{pretty(v)}</option>)}</select>
          <select aria-label="Filter colour" className="field" value={colour} onChange={(e) => filter(setColour)(e.target.value)}><option value="">All colours</option>{COLOURS.map((v) => <option key={v} value={v}>{v}</option>)}</select>
        </div>
        {rows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-xs">
              <thead><tr>{["Plate", "Make", "Model", "Body", "Colour", "Year", "Registered owner", "City", "Status"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{rows.map((row) => (
                <tr key={row.plate} className="hover:bg-canvas">
                  <td className="td num font-semibold">{row.plate}</td><td className="td">{row.make}</td><td className="td">{row.model}</td><td className="td">{pretty(row.body_type)}</td><td className="td">{row.colour}</td><td className="td num">{row.year ?? ""}</td><td className="td">{row.owner_name ?? ""}</td><td className="td">{row.owner_city ?? ""}</td><td className="td"><RegistryStatus status={row.status} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="No matching vehicles">Adjust the search or filters.</Empty>}
        <div className="flex items-center justify-between px-3 py-2 text-xs">
          <span className="num text-2xs text-muted">Page {page} of {pages}</span>
          <span className="flex gap-1"><button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></span>
        </div>
      </section>

      {drawer && (
        <aside className="panel w-full lg:w-[420px]">
          <div className="panel-head">Algorithm sandbox<button aria-label="Close sandbox" className="text-muted hover:text-ink" onClick={() => setDrawer(false)}><X size={16} /></button></div>
          <form className="space-y-2 border-b border-line p-3" onSubmit={runTest}>
            <label className="block"><span className="label">Partial plate, use ? for unknown</span><input className="field font-mono uppercase" value={plate} maxLength={16} onChange={(e) => setPlate(e.target.value.toUpperCase())} /></label>
            <label className="block"><span className="label">Character confidence <span className="num">{plateConf.toFixed(2)}</span></span><input type="range" min={0.3} max={1} step={0.01} value={plateConf} onChange={(e) => setPlateConf(Number(e.target.value))} className="w-full accent-[#1E3A5F]" /></label>
            <div className="grid grid-cols-2 gap-2">
              <label><span className="label">Colour</span><select className="field" value={testColour} onChange={(e) => setTestColour(e.target.value)}><option value="">Unknown</option>{COLOURS.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
              <label><span className="label">Body type</span><select className="field" value={testBody} onChange={(e) => setTestBody(e.target.value)}><option value="">Unknown</option>{BODY_TYPES.map((v) => <option key={v} value={v}>{pretty(v)}</option>)}</select></label>
            </div>
            <button className="btn btn-primary w-full" disabled={running}>{running ? "Matching…" : "Run matcher"}</button>
          </form>
          {result && <Shortlist key={`${result.query_plate}-${result.elapsed_ms}`} result={result} />}
        </aside>
      )}
    </div>
  );
}
