import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import { AppShell, NewCaseDialog, type View } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Loading, OUTCOME_ORDER } from "./components/ui";
import { isActiveRun } from "./lib/overview";
import { useOverview } from "./lib/useOverview";
import CaseWorkspace from "./pages/CaseWorkspace";
import Dashboard from "./pages/Dashboard";
import Investigations from "./pages/Investigations";
import Landing from "./pages/Landing";
import RegistryManager from "./pages/RegistryManager";
import Reports from "./pages/Reports";
import Traceability from "./pages/Traceability";
import VehicleInspector from "./pages/VehicleInspector";
import type { CaseDetail, CaseSummary, Entity, Health, VehicleSummary } from "./types";

const CASE_VIEWS: View[] = ["case", "inspector", "trace", "reports"];
const OVERVIEW_POLL_MS = 4000;

interface Route { view: View; caseId: string | null; vehicleId: string | null }

/** Existing `#/{case}/{view}/{vehicle}` links keep working. A bare URL opens the opening page. */
function readHash(): Route {
  const [first, second, third] = window.location.hash.replace(/^#\/?/, "").split("/");
  if (!first) return { view: "home", caseId: null, vehicleId: null };
  if (first === "dashboard") return { view: "dashboard", caseId: null, vehicleId: null };
  if (first === "investigations" || first === "registry") return { view: first, caseId: null, vehicleId: null };
  const view = second === "registry" || CASE_VIEWS.includes(second as View) ? (second as View) : "case";
  return { view, caseId: first, vehicleId: third || null };
}

function buildHash(view: View, caseId: string | null, vehicleId?: string | null) {
  if (view === "home") return "#/";
  if (!CASE_VIEWS.includes(view)) return `#/${view}`;
  if (!caseId) return "#/dashboard";
  return `#/${caseId}/${view}${view === "inspector" && vehicleId ? `/${vehicleId}` : ""}`;
}

export default function App() {
  const [route, setRoute] = useState<Route>(readHash);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [casesLoaded, setCasesLoaded] = useState(false);
  const [caseId, setCaseId] = useState<string | null>(route.caseId);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(Boolean(route.caseId));
  const [loadFailed, setLoadFailed] = useState(false);
  const [registryVersion, setRegistryVersion] = useState(0);
  const routeRef = useRef(route);
  routeRef.current = route;

  const { view, vehicleId } = route;
  const overviewEnabled = view === "dashboard" || view === "investigations";
  const overview = useOverview(cases, overviewEnabled && casesLoaded, registryVersion);

  const refreshHealth = useCallback(() => api.health().then(setHealth).catch((e: Error) => setError(e.message)), []);

  const refresh = useCallback(async () => {
    try {
      setLoadFailed(false);
      const list = await api.listCases();
      setCases(list);
      setCasesLoaded(true);
      const exists = Boolean(caseId && list.some((item) => item.id === caseId));
      const target = exists ? caseId : list[0]?.id ?? null;
      if (caseId && !exists) setError("That case link no longer exists. Showing the latest case.");
      if (target !== caseId) {
        setCaseId(target);
        if (routeRef.current.caseId) {
          const next = buildHash(routeRef.current.view, target);
          window.history.replaceState(null, "", next);
          setRoute(readHash());
        }
        if (target) return;
      }
      if (!target) {
        setDetail(null);
        setVehicles([]);
        setEntities([]);
        setLoading(false);
        return;
      }
      const [nextDetail, nextVehicles] = await Promise.all([api.getCase(target), api.vehicles(target)]);
      setDetail(nextDetail);
      setVehicles(nextVehicles.vehicles);
      setEntities(nextVehicles.entities);
      setLoading(false);
    } catch (e) {
      setError((e as Error).message);
      setLoadFailed(true);
      setCasesLoaded(true);
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    setDetail(null);
    setVehicles([]);
    setEntities([]);
    setLoading(Boolean(caseId));
  }, [caseId]);

  useEffect(() => { void refresh(); void refreshHealth(); }, [refresh, refreshHealth]);

  useEffect(() => {
    const onHash = () => {
      const next = readHash();
      setRoute(next);
      if (next.caseId) setCaseId(next.caseId);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const anyRunning = cases.some(isActiveRun);
  useEffect(() => {
    if (!overviewEnabled || !anyRunning) return;
    const timer = window.setInterval(() => void refresh(), OVERVIEW_POLL_MS);
    return () => window.clearInterval(timer);
  }, [overviewEnabled, anyRunning, refresh]);

  const go = useCallback((target: View, options: { caseId?: string; vehicleId?: string } = {}) => {
    const next = buildHash(target, options.caseId ?? caseId, options.vehicleId);
    if (options.caseId) setCaseId(options.caseId);
    if (window.location.hash === next) setRoute(readHash());
    else window.location.hash = next;
    window.scrollTo({ top: 0 });
  }, [caseId]);

  const openVehicle = useCallback((id: string, targetCase?: string) => go("inspector", { vehicleId: id, caseId: targetCase }), [go]);
  const openCase = useCallback((id: string) => go("case", { caseId: id }), [go]);

  const createCase = async (title: string) => {
    try {
      const created = await api.createCase(title);
      setCreating(false);
      setCases((list) => [created, ...list]);
      go("case", { caseId: created.id });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const review = entities.filter((entity) => entity.review_status === "proposed").length;
  const ordered = useMemo(() => [...vehicles].sort((a, b) =>
    OUTCOME_ORDER.indexOf(a.outcome ?? "UNREADABLE_PLATE") - OUTCOME_ORDER.indexOf(b.outcome ?? "UNREADABLE_PLATE")
    || (b.top_score ?? 0) - (a.top_score ?? 0) || b.known_chars - a.known_chars || b.frames_tracked - a.frames_tracked), [vehicles]);

  const banner = (
    <>
      {health?.models.assets && !health.models.assets.ready && (
        <div role="alert" className="border-b border-amber-300 bg-amber-50 px-4 py-1.5 text-xs text-amber-950">
          Analysis is unavailable. Missing {health.models.assets.missing.join(", ")}. From the backend folder, run <code className="num">{health.models.assets.install_command}</code>
        </div>
      )}
      {health?.models.assets?.ready && !health.models.assets.attributes_reid.installed && (
        <div role="status" className="border-b border-amber-300 bg-amber-50 px-4 py-1.5 text-xs text-amber-950">OpenCLIP weights are not installed, so make/model is Unknown and fine body type and visual link evidence are limited.</div>
      )}
      {error && (
        <div role="alert" className="flex items-center justify-between gap-2 border-b border-rose-200 bg-rose-50 px-4 py-1.5 text-xs text-rose-800">
          <span>{error}</span><button aria-label="Dismiss error" className="p-1" onClick={() => setError("")}><X size={16} /></button>
        </div>
      )}
    </>
  );

  if (view === "home") return <Landing cases={cases} casesReady={casesLoaded} health={health} onEnter={() => go("dashboard")} />;

  const needsCase = CASE_VIEWS.includes(view);

  return (
    <AppShell view={view} caseId={caseId} cases={cases} health={health} reviewCount={review} onNavigate={(next) => go(next)} onSelectCase={openCase} banner={banner}>
      <NewCaseDialog open={creating} onClose={() => setCreating(false)} onCreate={createCase} />
      <ErrorBoundary resetKey={`${caseId}-${view}-${vehicleId}`}>
        {loadFailed && !detail && needsCase ? (
          <div role="alert" className="panel px-4 py-8 text-center">
            <div className="text-xs font-semibold text-rose-800">Could not load this investigation</div>
            <button className="btn mt-3" onClick={() => { setLoading(true); setError(""); void refresh(); }}>Retry</button>
          </div>
        ) : needsCase && loading && !detail ? (
          <div className="panel"><Loading>Loading investigation…</Loading></div>
        ) : <>
          {view === "dashboard" && <Dashboard overview={overview} ready={casesLoaded} failed={loadFailed} cases={cases} health={health} onNewCase={() => setCreating(true)} onOpenCase={openCase} onOpenVehicle={openVehicle} onOpenTrace={(id) => go("trace", { caseId: id })} onOpenRegistry={() => go("registry")} onRetry={() => void refresh()} />}
          {view === "investigations" && <Investigations overview={overview} ready={casesLoaded} onNewCase={() => setCreating(true)} onOpenCase={openCase} />}
          {view === "case" && <CaseWorkspace detail={detail} loading={loading} vehicles={vehicles} onRefresh={refresh} onOpenVehicle={openVehicle} onOpenRegistry={() => go("registry")} onOpenTrace={() => go("trace")} onOpenReports={() => go("reports")} onNewCase={() => setCreating(true)} onError={setError} />}
          {view === "inspector" && (caseId
            ? <VehicleInspector caseId={caseId} vehicleId={vehicleId ?? ordered[0]?.id ?? null} vehicles={ordered} onOpenVehicle={openVehicle} onBack={() => go("case")} onChanged={refresh} onError={setError} formatHints={detail?.summary?.format_hints} />
            : <div className="panel p-6 text-center text-xs text-muted">Create an investigation first.</div>)}
          {view === "trace" && <Traceability caseId={caseId} caseTitle={detail?.title} entities={entities} clips={detail?.clips ?? []} onOpenVehicle={openVehicle} onChanged={refresh} onError={setError} />}
          {view === "reports" && <Reports detail={detail} onOpenCase={() => go("case")} />}
          {view === "registry" && <RegistryManager onError={setError} onRegistryChanged={() => { void refreshHealth(); void refresh(); setRegistryVersion((value) => value + 1); }} />}
        </>}
      </ErrorBoundary>
    </AppShell>
  );
}
