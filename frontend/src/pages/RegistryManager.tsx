import { FlaskConical, RefreshCw, Search, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Shortlist } from "../components/Shortlist";
import { Badge, Empty, Pagination, RegistryStatus, pretty } from "../components/ui";
import { BODY_TYPES, COLOURS, type MatchResult, type RegistryVehicle } from "../types";

const PAGE_SIZE = 25;
const PRESETS = [
  { label: "Full plate", plate: "MH12DE1433", colour: "white", body: "suv" },
  { label: "Partial, ambiguous", plate: "MH12DE14?3", colour: "white", body: "suv" },
  { label: "Too few characters", plate: "4829", colour: "red", body: "hatchback" },
  { label: "Attributes only", plate: "", colour: "white", body: "suv" },
  { label: "Not in registry", plate: "ZZ99QQ0000", colour: "white", body: "suv" },
];

type Load = "loading" | "ready" | "error";

export default function RegistryManager({ onError, onRegistryChanged }: { onError: (message: string) => void; onRegistryChanged: () => void }) {
  const [rows, setRows] = useState<RegistryVehicle[]>([]);
  const [total, setTotal] = useState(0);
  const [registryTotal, setRegistryTotal] = useState(0);
  const [syntheticCount, setSyntheticCount] = useState(0);
  const [load, setLoad] = useState<Load>("loading");
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [body, setBody] = useState("");
  const [colour, setColour] = useState("");
  const [source, setSource] = useState("");
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [notice, setNotice] = useState("");
  const [drawer, setDrawer] = useState(false);
  const [plate, setPlate] = useState(PRESETS[1].plate);
  const [plateConf, setPlateConf] = useState(0.9);
  const [testColour, setTestColour] = useState("white");
  const [testBody, setTestBody] = useState("suv");
  const [result, setResult] = useState<MatchResult | null>(null);
  const [running, setRunning] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const request = useRef(0);

  const fetchRows = useCallback(async () => {
    const id = ++request.current;
    setLoad("loading");
    try {
      const data = await api.registry({ q, status, body_type: body, colour, source, page, page_size: PAGE_SIZE });
      if (id !== request.current) return;
      setRows(data.items);
      setTotal(data.total);
      setRegistryTotal(data.registry_total);
      setSyntheticCount(data.synthetic_count);
      setLoad("ready");
    } catch (error) {
      if (id !== request.current) return;
      setLoadError((error as Error).message);
      setLoad("error");
    }
  }, [q, status, body, colour, source, page]);

  useEffect(() => {
    const timer = setTimeout(() => void fetchRows(), 150);
    return () => clearTimeout(timer);
  }, [fetchRows]);

  const upload = async (selected: File | undefined) => {
    if (!selected) return;
    if (mode === "replace" && !window.confirm(`Replace the entire registry with ${selected.name}? Existing rows will be deleted.`)) return;
    try {
      const outcome = await api.uploadRegistry(selected, mode);
      setNotice(`${selected.name}: ${outcome.inserted} added, ${outcome.updated} updated, ${outcome.rejected} rejected. Registry now holds ${outcome.total.toLocaleString()}.`);
      setPage(1);
      await fetchRows();
      onRegistryChanged();
    } catch (error) {
      onError((error as Error).message);
    }
  };

  const runMatch = async (value = plate, colourValue = testColour, bodyValue = testBody) => {
    setRunning(true);
    try {
      setResult(await api.matchTest({ plate: value, plate_confidence: plateConf, colour: colourValue || undefined, body_type: bodyValue || undefined, body_confidence: 0.8 }));
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void runMatch();
  };

  const pages = Math.max(Math.ceil(total / PAGE_SIZE), 1);
  const filter = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(1); };
  const allSynthetic = registryTotal > 0 && syntheticCount === registryTotal;

  return (
    <div className="relative grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
      <section className="panel min-w-0">
        <div className="panel-head flex-wrap">
          <span>Vehicle registry <span className="num font-normal text-muted">{registryTotal ? registryTotal.toLocaleString() : ""}</span></span>
          <span className="flex flex-wrap items-center gap-1.5">
            <select aria-label="Upload mode" className="field w-auto" value={mode} onChange={(e) => setMode(e.target.value as "merge" | "replace")}>
              <option value="merge">Merge</option><option value="replace">Replace all</option>
            </select>
            <button className="btn" onClick={() => file.current?.click()}><Upload size={16} /> Upload CSV/JSON</button>
            <input ref={file} type="file" accept=".csv,.json" className="hidden" onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} />
            <button className="btn btn-primary" onClick={() => setDrawer(!drawer)} aria-expanded={drawer}><FlaskConical size={16} /> Matcher sandbox</button>
          </span>
        </div>
        {syntheticCount > 0 && (
          <div className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            {allSynthetic ? "This registry is entirely synthetic test data." : `${syntheticCount.toLocaleString()} of ${registryTotal.toLocaleString()} vehicles are synthetic test data.`} People and plates are fictional. Upload a real registry to identify real vehicles.
          </div>
        )}
        {notice && <div className="border-b border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900">{notice}</div>}
        <div className="grid gap-2 border-b border-line p-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr_1fr]">
          <label className="relative"><Search size={16} className="absolute left-2 top-1.5 text-muted" /><input aria-label="Search registry" className="field pl-7" placeholder="Search plate, make, model, owner" value={q} onChange={(e) => filter(setQ)(e.target.value)} /></label>
          <select aria-label="Filter status" className="field" value={status} onChange={(e) => filter(setStatus)(e.target.value)}><option value="">All statuses</option><option value="ACTIVE">Active</option><option value="STOLEN_ALERT">Stolen alert</option><option value="EXPIRED">Expired</option></select>
          <select aria-label="Filter body" className="field" value={body} onChange={(e) => filter(setBody)(e.target.value)}><option value="">All body types</option>{BODY_TYPES.map((v) => <option key={v} value={v}>{pretty(v)}</option>)}</select>
          <select aria-label="Filter colour" className="field" value={colour} onChange={(e) => filter(setColour)(e.target.value)}><option value="">All colours</option>{COLOURS.map((v) => <option key={v} value={v}>{v}</option>)}</select>
          <select aria-label="Filter source" className="field" value={source} onChange={(e) => filter(setSource)(e.target.value)}><option value="">All sources</option><option value="synthetic">Synthetic</option><option value="uploaded">Uploaded</option></select>
        </div>
        {load === "error" ? (
          <div role="alert" className="px-4 py-8 text-center">
            <div className="text-xs font-semibold text-rose-800">Could not load the registry</div>
            <div className="mx-auto mt-1 max-w-md text-xs text-muted">{loadError}</div>
            <button className="btn mt-3" onClick={() => void fetchRows()}><RefreshCw size={16} /> Retry</button>
          </div>
        ) : load === "loading" && rows.length === 0 ? (
          <div role="status" className="px-4 py-8 text-center text-xs text-muted">Loading registry…</div>
        ) : rows.length ? (
          <div className={`overflow-x-auto ${load === "loading" ? "opacity-60" : ""}`} aria-busy={load === "loading"}>
            <table className="w-full min-w-[860px] border-collapse text-xs">
              <thead><tr>{["Plate", "Make", "Model", "Body", "Colour", "Year", "Registered owner", "City", "Status", "Source"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{rows.map((row) => (
                <tr key={row.plate} className="hover:bg-canvas">
                  <td className="td num font-semibold">{row.plate}</td><td className="td">{row.make}</td><td className="td">{row.model}</td><td className="td">{pretty(row.body_type)}</td><td className="td">{row.colour}</td><td className="td num">{row.year ?? ""}</td><td className="td">{row.owner_name ?? ""}</td><td className="td">{row.owner_city ?? ""}</td><td className="td"><RegistryStatus status={row.status} /></td><td className="td"><Badge tone={row.source === "synthetic" ? "amber" : "navy"}>{row.source}</Badge></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="No matching vehicles">Adjust the search or filters.</Empty>}
        {load !== "error" && <div className="border-t border-line"><Pagination page={page} pages={pages} total={total} label="vehicles" onChange={setPage} /></div>}
      </section>

      {drawer && (
        <aside className="panel w-full min-w-0 lg:w-[420px]">
          <div className="panel-head">Algorithm sandbox<button aria-label="Close sandbox" className="text-muted hover:text-ink" onClick={() => setDrawer(false)}><X size={16} /></button></div>
          <div className="flex flex-wrap gap-1 border-b border-line p-2">
            {PRESETS.map((preset) => (
              <button key={preset.label} className="btn" onClick={() => { setPlate(preset.plate); setTestColour(preset.colour); setTestBody(preset.body); void runMatch(preset.plate, preset.colour, preset.body); }}>{preset.label}</button>
            ))}
          </div>
          <form className="space-y-2 border-b border-line p-3" onSubmit={submit}>
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
