import { Database, FileText, LayoutDashboard, FolderSearch, ScanSearch, Share2, SquareStack, LogOut, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { CaseSummary, Health } from "../types";
import { Logo } from "./Logo";

export type View = "home" | "dashboard" | "investigations" | "case" | "inspector" | "trace" | "reports" | "registry";

const OVERVIEW: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "investigations", label: "Investigations", icon: FolderSearch },
];
const CASE_ITEMS: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "case", label: "Case workspace", icon: SquareStack },
  { id: "inspector", label: "Vehicle inspector", icon: ScanSearch },
  { id: "trace", label: "Cross-camera trace", icon: Share2 },
  { id: "reports", label: "Reports", icon: FileText },
];
const REFERENCE: { id: View; label: string; icon: LucideIcon }[] = [{ id: "registry", label: "Registry", icon: Database }];

function NavItem({ item, active, disabled, badge, onClick }: {
  item: { id: View; label: string; icon: LucideIcon };
  active: boolean;
  disabled?: boolean;
  badge?: number;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`flex min-h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-evidence px-2.5 py-1.5 text-left text-xs font-medium lg:w-full ${
        active ? "bg-accent text-white" : "text-shell-muted hover:bg-shell-raised hover:text-shell-text"
      } disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <Icon size={15} aria-hidden="true" className="shrink-0" />
      <span className="min-w-0 flex-1">{item.label}</span>
      {badge ? <span className={`num rounded-evidence px-1 text-2xs ${active ? "bg-white/20" : "bg-shell-raised text-shell-text"}`} aria-label={`${badge} to review`}>{badge}</span> : null}
    </button>
  );
}

export function NewCaseDialog({ open, onClose, onCreate }: { open: boolean; onClose: () => void; onCreate: (title: string) => Promise<void> }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && !ref.current?.open) {
      ref.current?.showModal();
      ref.current?.querySelector("input")?.focus();
    }
    if (!open && ref.current?.open) ref.current.close();
  }, [open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      await onCreate(title.trim());
      setTitle("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="new-case-title" className="w-[min(420px,calc(100vw-32px))] rounded-evidence border border-line bg-surface p-0 text-ink">
      <form onSubmit={submit}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 id="new-case-title" className="text-sm font-semibold">New investigation</h2>
          <button type="button" aria-label="Close" className="p-1 text-muted hover:text-ink" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="space-y-1 px-4 py-3">
          <label htmlFor="new-case-name" className="label">Investigation name</label>
          <input id="new-case-name" className="field" placeholder="For example, Ring Road sighting" value={title} onChange={(event) => setTitle(event.target.value)} />
          <p className="text-2xs text-muted">You can add CCTV clips on the next screen.</p>
        </div>
        <div className="flex justify-end gap-1.5 border-t border-line px-4 py-3">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!title.trim() || busy}>{busy ? "Creating…" : "Create investigation"}</button>
        </div>
      </form>
    </dialog>
  );
}

export function AppShell({ view, caseId, cases, health, reviewCount, username, onSignOut, onNavigate, onSelectCase, banner, children }: {
  view: View;
  username?: string | null;
  onSignOut?: () => void;
  caseId: string | null;
  cases: CaseSummary[];
  health: Health | null;
  reviewCount: number;
  onNavigate: (view: View) => void;
  onSelectCase: (id: string) => void;
  banner?: ReactNode;
  children: ReactNode;
}) {
  const allSynthetic = Boolean(health && health.registry_count > 0 && health.synthetic_count === health.registry_count);
  const select = (
    <select aria-label="Current investigation" className="min-h-8 w-full min-w-0 rounded-evidence border border-shell-line bg-shell-raised px-2 py-1.5 text-xs text-shell-text" value={caseId ?? ""} disabled={!cases.length} onChange={(event) => onSelectCase(event.target.value)}>
      {!cases.length && <option value="">No investigations</option>}
      {cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
    </select>
  );
  const item = (entry: { id: View; label: string; icon: LucideIcon }, scoped = false) => (
    <NavItem key={entry.id} item={entry} active={view === entry.id} disabled={scoped && !caseId} badge={entry.id === "trace" ? reviewCount : undefined} onClick={() => onNavigate(entry.id)} />
  );

  return (
    <div className="min-h-full lg:pl-56">
      <a href="#main-content" className="skip-link" onClick={(event) => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to main content</a>
      <aside data-tour="nav" className="on-shell border-b border-shell-line bg-shell text-shell-text lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-56 lg:flex-col lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2 px-3 py-2.5 lg:px-4 lg:py-4">
          <a href="#/" title="Back to the VITRA home page" className="rounded-evidence"><Logo size={26} tagline taglineClassName="hidden lg:block" /></a>
          <div className="ml-auto min-w-0 max-w-[58%] lg:hidden">{select}</div>
        </div>
        <nav aria-label="Workbench" className="flex flex-wrap gap-1 px-2 pb-2 lg:flex-1 lg:flex-col lg:flex-nowrap lg:gap-0 lg:overflow-y-auto lg:px-2 lg:pb-3">
          <div className="contents lg:block lg:space-y-0.5">{OVERVIEW.map((entry) => item(entry))}</div>
          <div className="contents lg:mt-4 lg:block lg:space-y-0.5">
            <div className="hidden px-2.5 pb-1 text-2xs font-semibold text-shell-muted lg:block">Current investigation</div>
            <div className="hidden px-1 pb-1.5 lg:block">{select}</div>
            {CASE_ITEMS.map((entry) => item(entry, true))}
          </div>
          <div className="contents lg:mt-4 lg:block lg:space-y-0.5">
            <div className="hidden px-2.5 pb-1 text-2xs font-semibold text-shell-muted lg:block">Reference data</div>
            {REFERENCE.map((entry) => item(entry))}
          </div>
        </nav>
        {health && (
          <dl className="hidden space-y-0.5 border-t border-shell-line px-4 py-3 text-2xs text-shell-muted lg:block">
            <div className="flex justify-between gap-2"><dt>Registry</dt><dd className="num">{health.registry_count.toLocaleString()}{allSynthetic ? " synthetic" : ""}</dd></div>
            <div className="flex justify-between gap-2"><dt>Compute</dt><dd className="num">{health.models.device}</dd></div>
            <div className="flex justify-between gap-2"><dt>Pipeline</dt><dd className="num">v{health.pipeline_version}</dd></div>
          </dl>
        )}
        {onSignOut && (
          <div className="flex items-center gap-2 border-t border-shell-line px-3 py-2 text-2xs text-shell-muted lg:px-4 lg:py-3">
            <span className="min-w-0 flex-1 truncate">Signed in as <span className="font-semibold text-shell-text">{username}</span></span>
            <button type="button" onClick={onSignOut} className="inline-flex items-center gap-1 rounded-evidence px-1.5 py-1 text-shell-text hover:bg-shell-raised hover:text-white"><LogOut size={13} /> Sign out</button>
          </div>
        )}
      </aside>
      {banner}
      <main id="main-content" tabIndex={-1} className="mx-auto min-w-0 max-w-[1680px] space-y-3 px-3 py-3 outline-none sm:px-4 sm:py-4 lg:px-5">
        {children}
      </main>
    </div>
  );
}
