import { AlertTriangle, Braces, Download, ExternalLink, FileText, Table2 } from "lucide-react";
import { useEffect, useState } from "react";
import { exportUrl, reportHtmlUrl, reportPdfUrl } from "../api/client";
import { Badge, Empty, Loading, Notice, PageHeader, shortHash } from "../components/ui";
import { actionLabel, analysisState, isActiveRun } from "../lib/overview";
import type { CaseDetail } from "../types";

export default function Reports({ detail, onOpenCase }: { detail: CaseDetail | null; onOpenCase: () => void }) {
  const [clipId, setClipId] = useState("");
  const caseId = detail?.id;
  const [preview, setPreview] = useState<{ state: "loading" | "ready" | "failed"; html: string }>({ state: "loading", html: "" });
  const [attempt, setAttempt] = useState(0);
  const completed = Boolean(detail?.has_completed_run);
  const version = detail?.updated_at;
  useEffect(() => setClipId(""), [caseId]);

  useEffect(() => {
    if (!caseId || !completed) return;
    const controller = new AbortController();
    setPreview({ state: "loading", html: "" });
    fetch(reportHtmlUrl(caseId, clipId || undefined), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then((html) => setPreview({ state: "ready", html }))
      .catch((error: Error) => { if (error.name !== "AbortError") setPreview({ state: "failed", html: "" }); });
    return () => controller.abort();
  }, [caseId, clipId, completed, version, attempt]);

  if (!detail) return <div className="panel"><Empty title="No investigation selected">Choose an investigation to view its reports.</Empty></div>;
  const scope = clipId || undefined;
  const hasResults = Boolean(detail.has_completed_run);
  const state = analysisState(detail);
  const summary = detail.summary;
  const gaps = summary?.coverage?.filter((row) => row.status === "no_coverage") ?? [];

  return (
    <>
      <PageHeader eyebrow="Reports" title={detail.title} description="Preview the forensic report, then download it with its chain of custody and audit log."
        actions={<>{detail.clips.some((clip) => clip.synthetic) && <Badge tone="amber" title="Clips in this case are synthetic test fixtures">Demo evidence</Badge>}<Badge tone={state.tone}>{state.label}</Badge></>} />
      {!hasResults ? (
        <div className="panel"><Empty title="No completed analysis">Reports become available after an analysis finishes.<div><button className="btn mt-2" onClick={onOpenCase}>Open case workspace</button></div></Empty></div>
      ) : (
        <>
          {isActiveRun(detail) && <Notice tone="accent">A new analysis is running. These reports use the previous completed run.</Notice>}
          {gaps.length > 0 && (
            <Notice icon={<AlertTriangle size={15} />} title="Registry coverage gap">
              {gaps.map((row) => `${row.camera_label} (${row.format_label}) has 0 compatible records`).join("; ")}. Affected plates are reported as not searched, not as no-match results.
            </Notice>
          )}
          <div className="grid items-start gap-3 xl:grid-cols-[300px_minmax(0,1fr)]">
            <div className="min-w-0 space-y-3">
              <section className="panel" aria-labelledby="report-scope">
                <div className="panel-head"><h2 id="report-scope">Report scope</h2></div>
                <div className="space-y-2 p-3">
                  <label className="block"><span className="label">Coverage</span>
                    <select className="field" value={clipId} onChange={(event) => setClipId(event.target.value)}>
                      <option value="">Entire case ({detail.clips.length} clip{detail.clips.length === 1 ? "" : "s"})</option>
                      {detail.clips.map((clip) => <option key={clip.id} value={clip.id}>{clip.camera_label}</option>)}
                    </select>
                  </label>
                  <div className="grid gap-1.5">
                    <a className="btn btn-primary justify-start" href={reportPdfUrl(detail.id, false, scope)}><Download size={15} /> Download PDF</a>
                    <a className="btn justify-start" href={reportPdfUrl(detail.id, true, scope)}><FileText size={15} /> PDF with appendix</a>
                    <a className="btn justify-start" href={reportHtmlUrl(detail.id, scope)} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open HTML report</a>
                    <a className="btn justify-start" href={exportUrl(detail.id, "csv", scope)}><Table2 size={15} /> Export CSV</a>
                    <a className="btn justify-start" href={exportUrl(detail.id, "json", scope)}><Braces size={15} /> Export JSON</a>
                  </div>
                </div>
              </section>
              <section className="panel" aria-labelledby="custody">
                <div className="panel-head"><h2 id="custody">Chain of custody</h2></div>
                <ul className="divide-y divide-line">
                  {detail.clips.map((clip) => (
                    <li key={clip.id} className="px-3 py-1.5 text-2xs">
                      <div className="flex items-center justify-between gap-1 font-medium"><span className="truncate text-xs">{clip.camera_label}</span>{clip.synthetic && <Badge tone="amber">Demo evidence</Badge>}</div>
                      <div className="num text-muted" title={clip.sha256}>SHA-256 {shortHash(clip.sha256)}</div>
                      <div className={clip.recorded_at ? "num text-muted" : "text-amber-900"}>{clip.recorded_at ? new Date(clip.recorded_at).toLocaleString() : "Capture time missing"}</div>
                    </li>
                  ))}
                </ul>
              </section>
              <details className="panel">
                <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">Audit log <span className="num font-normal text-muted">{detail.audit.length}</span></summary>
                <ol className="max-h-72 divide-y divide-line overflow-y-auto border-t border-line">
                  {[...detail.audit].reverse().map((entry) => (
                    <li key={entry.id} className="px-3 py-1.5 text-2xs">
                      <div className="font-medium">{actionLabel(entry.action)}</div>
                      <div className="num text-muted">{new Date(entry.created_at).toLocaleString()} · {entry.actor}</div>
                      {entry.note && <div className="break-words text-muted">{entry.note}</div>}
                    </li>
                  ))}
                </ol>
              </details>
            </div>
            <section className="panel min-w-0" aria-labelledby="report-preview">
              <div className="panel-head"><h2 id="report-preview">Report preview</h2><span className="font-normal text-muted">{scope ? detail.clips.find((clip) => clip.id === scope)?.camera_label : "Entire case"}</span></div>
              {preview.state === "loading" && <Loading>Generating report preview…</Loading>}
              {preview.state === "failed" && (
                <div role="alert"><Empty title="Report preview could not be loaded">Downloads may still work.<div><button className="btn mt-2" onClick={() => setAttempt((value) => value + 1)}>Retry</button></div></Empty></div>
              )}
              {preview.state === "ready" && <iframe key={`${detail.id}-${scope ?? "case"}`} title="Forensic report preview" srcDoc={preview.html} sandbox="" className="h-[75vh] min-h-[480px] w-full rounded-b-evidence bg-white" />}
            </section>
          </div>
        </>
      )}
    </>
  );
}
