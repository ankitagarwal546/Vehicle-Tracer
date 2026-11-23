import { ArrowLeft, ArrowRight, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const STEPS = [
  { target: "next", title: "Start here", body: "This card always tells you the single most useful thing to do next. Press its button to go straight there." },
  { target: "pipeline", title: "How evidence moves", body: "Every clip goes through five stages. The numbers show how much of your casework has reached each one." },
  { target: "stats", title: "Your workload", body: "See how many vehicles were tracked, how many plates could be read, and what is waiting for you. Tap any small i icon for a plain explanation." },
  { target: "insights", title: "What needs attention", body: "VITRA turns findings into short sentences. Each card links to the exact place where you can fix or review it." },
  { target: "table", title: "Your investigations", body: "Every case with its plates, registry coverage, analysis state and review status. Click a name to open it." },
  { target: "registry", title: "Can the registry help?", body: "A plate can only be searched if the registry holds that plate format. Warnings here explain why a plate was not searched." },
  { target: "nav", title: "Move around", body: "Open a case workspace, inspect a vehicle, review cross-camera links, or preview reports from here." },
];
const CARD_WIDTH = 330;
const CARD_HEIGHT = 200;
const PADDING = 6;

export function GuidedTour({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = STEPS[index];
  const last = index === STEPS.length - 1;

  const locate = useCallback(() => {
    const element = document.querySelector(`[data-tour="${STEPS[index].target}"]`);
    if (element) setRect(element.getBoundingClientRect());
  }, [index]);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  useLayoutEffect(() => {
    const element = document.querySelector(`[data-tour="${step.target}"]`);
    element?.scrollIntoView({ block: "center", behavior: "auto" });
    locate();
    next.current?.focus();
  }, [step.target, locate]);

  useEffect(() => {
    window.addEventListener("resize", locate);
    window.addEventListener("scroll", locate, { passive: true, capture: true });
    return () => {
      window.removeEventListener("resize", locate);
      window.removeEventListener("scroll", locate, { capture: true });
    };
  }, [locate]);

  const advance = () => (last ? dialog.current?.close() : setIndex(index + 1));
  const back = () => setIndex(Math.max(index - 1, 0));

  const viewportW = window.innerWidth;
  const viewportH = window.innerHeight;
  const spot = rect ? {
    top: Math.max(rect.top - PADDING, 2),
    left: Math.max(rect.left - PADDING, 2),
    width: Math.min(rect.width + PADDING * 2, viewportW - 4),
    height: Math.min(rect.height + PADDING * 2, viewportH - 4),
  } : null;
  const width = Math.min(CARD_WIDTH, viewportW - 24);
  let cardTop = viewportH - CARD_HEIGHT - 12;
  let cardLeft = (viewportW - width) / 2;
  if (spot) {
    const below = spot.top + spot.height + 10;
    const above = spot.top - CARD_HEIGHT - 10;
    const right = spot.left + spot.width + 12;
    if (below + CARD_HEIGHT < viewportH) cardTop = below;
    else if (above > 8) cardTop = above;
    else if (right + width < viewportW) {
      cardLeft = right;
      cardTop = Math.max(Math.min(spot.top, viewportH - CARD_HEIGHT - 12), 12);
    }
    if (cardLeft === (viewportW - width) / 2) cardLeft = Math.min(Math.max(spot.left, 12), viewportW - width - 12);
  }

  return (
    <dialog ref={dialog} aria-labelledby="tour-title" aria-describedby="tour-body" onClose={onClose}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight" && !last) setIndex(index + 1);
        if (event.key === "ArrowLeft") back();
      }}
      className="tour-dialog fixed inset-0 m-0 h-full max-h-none w-full max-w-none overflow-hidden border-0 bg-transparent p-0 text-ink">
      {spot && <div aria-hidden="true" className="tour-spot pointer-events-none fixed rounded-evidence" style={spot} />}
      <div className="fixed rounded-xl border border-accent-line bg-[#1E1838] p-4 shadow-2xl shadow-black/60" style={{ top: cardTop, left: cardLeft, width }}>
        <div className="flex items-center justify-between gap-2">
          <span className="num text-2xs font-semibold text-signal">Step {index + 1} of {STEPS.length}</span>
          <button type="button" aria-label="Close tour" className="flex h-7 w-7 items-center justify-center rounded-full text-muted hover:bg-accent-tint hover:text-white" onClick={() => dialog.current?.close()}><X size={15} /></button>
        </div>
        <h2 id="tour-title" className="mt-1 text-base font-semibold text-white">{step.title}</h2>
        <p id="tour-body" className="mt-1 text-[13px] leading-5 text-[#D6D2E8]">{step.body}</p>
        <div className="mt-3 flex items-center justify-between gap-2">
          <div aria-hidden="true" className="flex gap-1">{STEPS.map((item, dot) => <span key={item.target} className={`h-1.5 rounded-full transition-all ${dot === index ? "w-4 bg-signal" : "w-1.5 bg-slate-400"}`} />)}</div>
          <div className="flex gap-1.5">
            <button type="button" className="btn" disabled={index === 0} onClick={back}><ArrowLeft size={14} /> Back</button>
            <button ref={next} type="button" className="btn btn-primary" onClick={advance}>{last ? "Finish" : "Next"}{!last && <ArrowRight size={14} />}</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
