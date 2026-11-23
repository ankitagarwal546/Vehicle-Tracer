import { Download, FileText, Plus, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, reportHtmlUrl, reportPdfUrl } from "./api/client";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Badge, OUTCOME_ORDER } from "./components/ui";
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

function readHash(): { caseId: string | null; view: View; vehicleId: string | null } {
  const [caseId, view, vehicleId] = window.location.hash.replace(/^#\/?/, "").split("/");
  return {
    caseId: caseId || null,
    view: VIEWS.some((item) => item.id === view) ? (view as View) : "case",
    vehicleId: vehicleId || null,
  };
}

export default function App() {
  const initial = useRef(readHash());
  const [view, setView] = useState<View>(initial.current.view);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [caseId, setCaseId] = useState<string | null>(initial.current.caseId);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [vehicleId, setVehicleId] = useState<string | null>(initial.current.vehicleId);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");

  const refreshHealth = useCallback(() => api.health().then(setHealth).catch((e: Error) => setError(e.message)), []);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listCases();
      setCases(list);
      const target = caseId && list.some((item) => item.id === caseId) ? caseId : list[0]?.id ?? null;
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

  useEffect(() => {
    const next = caseId ? `#/${caseId}/${view}${view === "inspector" && vehicleId ? `/${vehicleId}` : ""}` : "";
    if (window.location.hash !== next) window.history.replaceState(null, "", next || window.location.pathname);
  }, [caseId, view, vehicleId]);

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
  const review = entities.filter((entity) => entity.review_status === "proposed").length;
  const ordered = useMemo(() => [...vehicles].sort((a, b) =>
    OUTCOME_ORDER.indexOf(a.outcome ?? "UNREADABLE_PLATE") - OUTCOME_ORDER.indexOf(b.outcome ?? "UNREADABLE_PLATE")
    || (b.top_score ?? 0) - (a.top_score ?? 0) || b.known_chars - a.known_chars || b.frames_tracked - a.frames_tracked), [vehicles]);

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-line bg-white">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 sm:px-4">
          <div className="text-sm font-semibold tracking-tight text-navy">Vehicle Tracer</div>
          <span className="hidden h-4 w-px bg-line sm:block" />
          <select aria-label="Select case" className="field w-auto min-w-0 max-w-[200px]" value={caseId ?? ""} onChange={(e) => selectCase(e.target.value)}>
            {!cases.length && <option value="">No cases</option>}
            {cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
          {creating ? (
            <form className="flex items-center gap-1" onSubmit={createCase}>
              <input autoFocus aria-label="Case title" className="field w-40" placeholder="Case title" value={title} onChange={(e) => setTitle(e.target.value)} />
              <button className="btn btn-primary">Create</button>
              <button type="button" className="btn" aria-label="Cancel" onClick={() => setCreating(false)}><X size={16} /></button>
            </form>
          ) : <button className="btn" onClick={() => setCreating(true)}><Plus size={16} /> New case</button>}
          {detail && <Badge tone={statusTone(detail.status)}>{detail.status.toLowerCase()}</Badge>}
          <div className="flex w-full flex-wrap items-center gap-1.5 md:ml-auto md:w-auto">
            {health && <span className="num mr-1 hidden text-2xs text-muted 2xl:inline">{health.models.device} · registry {health.registry_count.toLocaleString()}{health.synthetic_count === health.registry_count ? " synthetic" : ""} · v{health.pipeline_version}</span>}
            {caseId && hasResults ? (
              <>
                <a className="btn" href={reportHtmlUrl(caseId)} target="_blank" rel="noreferrer"><FileText size={16} /> HTML report</a>
                <a className="btn btn-primary" href={reportPdfUrl(caseId)}><Download size={16} /> PDF report</a>
                <a className="btn" href={reportPdfUrl(caseId, true)}>PDF + appendix</a>
              </>
            ) : (
              <>
                <button className="btn" disabled title="Available after analysis"><FileText size={16} /> HTML report</button>
                <button className="btn btn-primary" disabled title="Available after analysis"><Download size={16} /> PDF report</button>
              </>
            )}
          </div>
        </div>
        <nav className="grid grid-cols-2 gap-x-1 px-2 sm:flex sm:px-3" aria-label="Workbench views">
          {VIEWS.map((item) => (
            <button key={item.id} onClick={() => setView(item.id)} aria-current={view === item.id ? "page" : undefined}
              className={`border-b-2 px-2.5 py-1.5 text-left text-xs font-medium sm:whitespace-nowrap ${view === item.id ? "border-navy text-navy" : "border-transparent text-muted hover:text-ink"}`}>
              {item.label}
              {item.id === "trace" && review > 0 && <span className="num ml-1 text-2xs text-amber-800">{review}</span>}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div role="alert" className="flex items-center justify-between gap-2 border-b border-rose-200 bg-rose-50 px-4 py-1.5 text-xs text-rose-800">
          <span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button>
        </div>
      )}

      <main className="min-w-0 flex-1 p-2 sm:p-4">
        <ErrorBoundary resetKey={`${caseId}-${view}-${vehicleId}`}>
        {view === "case" && <CaseWorkspace detail={detail} vehicles={vehicles} onRefresh={refresh} onOpenVehicle={openVehicle} onError={setError} />}
        {view === "inspector" && (caseId
          ? <VehicleInspector caseId={caseId} vehicleId={vehicleId ?? ordered[0]?.id ?? null} vehicles={ordered} onOpenVehicle={openVehicle} onBack={() => setView("case")} onChanged={refresh} onError={setError} />
          : <div className="panel p-6 text-center text-xs text-muted">Create a case first.</div>)}
        {view === "trace" && <Traceability caseId={caseId} entities={entities} clipCount={detail?.clips.length ?? 0} onOpenVehicle={openVehicle} onChanged={refresh} onError={setError} />}
        {view === "registry" && <RegistryManager onError={setError} onRegistryChanged={refreshHealth} />}
        </ErrorBoundary>
      </main>
    </div>
  );
}
