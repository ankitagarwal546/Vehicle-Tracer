import { Download, FileText, Plus, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, reportHtmlUrl, reportPdfUrl } from "./api/client";
import { Badge } from "./components/ui";
import CaseWorkspace from "./pages/CaseWorkspace";
import RegistryManager from "./pages/RegistryManager";
import Traceability from "./pages/Traceability";
import VehicleInspector from "./pages/VehicleInspector";
import type { CaseDetail, CaseSummary, Entity, Health, VehicleSummary } from "./types";

type View = "case" | "inspector" | "trace" | "registry";
const VIEWS: { id: View; label: string }[] = [
  { id: "case", label: "Case workspace" },
  { id: "inspector", label: "Vehicle inspector" },
  { id: "trace", label: "Cross-camera trace" },
  { id: "registry", label: "Registry and sandbox" },
];

const statusTone = (status?: string) =>
  status === "COMPLETED" ? "emerald" : status === "FAILED" ? "crimson" : status === "RUNNING" || status === "QUEUED" ? "amber" : "slate";

export default function App() {
  const [view, setView] = useState<View>("case");
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [vehicleId, setVehicleId] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");

  const refreshHealth = useCallback(() => api.health().then(setHealth).catch((e: Error) => setError(e.message)), []);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listCases();
      setCases(list);
      const target = caseId ?? list[0]?.id ?? null;
      if (target !== caseId) setCaseId(target);
      if (!target) return;
      const [nextDetail, nextVehicles] = await Promise.all([api.getCase(target), api.vehicles(target)]);
      setDetail(nextDetail);
      setVehicles(nextVehicles.vehicles);
      setEntities(nextVehicles.entities);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [caseId]);

  useEffect(() => { void refresh(); void refreshHealth(); }, [refresh, refreshHealth]);

  const selectCase = (id: string) => {
    setCaseId(id);
    setDetail(null);
    setVehicles([]);
    setEntities([]);
    setVehicleId(null);
    setView("case");
  };

  const createCase = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      const created = await api.createCase(title.trim());
      setTitle("");
      setCreating(false);
      selectCase(created.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const openVehicle = useCallback((id: string) => { setVehicleId(id); setView("inspector"); }, []);
  const hasResults = detail?.status === "COMPLETED";

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-white">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
          <div className="text-sm font-semibold tracking-tight text-navy">Vehicle Tracer</div>
          <span className="hidden h-4 w-px bg-line sm:block" />
          <select aria-label="Select case" className="field w-auto max-w-[220px]" value={caseId ?? ""} onChange={(e) => selectCase(e.target.value)}>
            {!cases.length && <option value="">No cases</option>}
            {cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          {creating ? (
            <form className="flex items-center gap-1" onSubmit={createCase}>
              <input autoFocus aria-label="Case title" className="field w-44" placeholder="Case title" value={title} onChange={(e) => setTitle(e.target.value)} />
              <button className="btn btn-primary">Create</button>
              <button type="button" className="btn" aria-label="Cancel" onClick={() => setCreating(false)}><X size={16} /></button>
            </form>
          ) : <button className="btn" onClick={() => setCreating(true)}><Plus size={16} /> New case</button>}
          {detail && <Badge tone={statusTone(detail.status)}>{detail.status.toLowerCase()}</Badge>}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {health && <span className="num hidden text-2xs text-muted xl:inline">{health.models.device} · registry {health.registry_count} · v{health.pipeline_version}</span>}
            {caseId && hasResults ? (
              <>
                <a className="btn" href={reportHtmlUrl(caseId)} target="_blank" rel="noreferrer"><FileText size={16} /> Preview HTML report</a>
                <a className="btn btn-primary" href={reportPdfUrl(caseId)}><Download size={16} /> Download PDF report</a>
              </>
            ) : (
              <>
                <button className="btn" disabled title="Available after analysis"><FileText size={16} /> Preview HTML report</button>
                <button className="btn btn-primary" disabled title="Available after analysis"><Download size={16} /> Download PDF report</button>
              </>
            )}
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3" aria-label="Workbench views">
          {VIEWS.map((item) => (
            <button key={item.id} onClick={() => setView(item.id)} aria-current={view === item.id ? "page" : undefined}
              className={`whitespace-nowrap border-b-2 px-2.5 py-1.5 text-xs font-medium ${view === item.id ? "border-navy text-navy" : "border-transparent text-muted hover:text-ink"}`}>
              {item.label}
              {item.id === "trace" && entities.length > 0 && <span className="num ml-1 text-2xs">{entities.length}</span>}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div role="alert" className="flex items-center justify-between gap-2 border-b border-rose-200 bg-rose-50 px-4 py-1.5 text-xs text-rose-800">
          <span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button>
        </div>
      )}

      <main className="flex-1 p-3 sm:p-4">
        {view === "case" && <CaseWorkspace detail={detail} vehicles={vehicles} onRefresh={refresh} onOpenVehicle={openVehicle} onError={setError} />}
        {view === "inspector" && (caseId
          ? <VehicleInspector caseId={caseId} vehicleId={vehicleId ?? vehicles[0]?.id ?? null} onBack={() => setView("case")} onChanged={refresh} onError={setError} />
          : <div className="panel p-6 text-center text-xs text-muted">Create a case first.</div>)}
        {view === "trace" && <Traceability entities={entities} clipCount={detail?.clips.length ?? 0} onOpenVehicle={openVehicle} />}
        {view === "registry" && <RegistryManager onError={setError} onRegistryChanged={refreshHealth} />}
      </main>
    </div>
  );
}
