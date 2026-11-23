import { Info } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

const WIDTH = 248;

/** A plain-language explanation that opens on hover, keyboard focus or tap. */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  const show = useCallback(() => {
    const box = button.current?.getBoundingClientRect();
    if (!box) return;
    const left = Math.min(Math.max(box.left + box.width / 2 - WIDTH / 2, 8), window.innerWidth - WIDTH - 8);
    setPosition(box.bottom + 150 > window.innerHeight
      ? { left, bottom: window.innerHeight - box.top + 6 }
      : { left, top: box.bottom + 6 });
  }, []);
  const hide = useCallback(() => setPosition(null), []);

  useEffect(() => {
    if (!position) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") hide(); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, { passive: true, capture: true });
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, { capture: true });
    };
  }, [position, hide]);

  return (
    <span className="inline-flex align-middle">
      <button ref={button} type="button" aria-label={`What does ${label} mean?`} aria-describedby={position ? id : undefined}
        onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}
        onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (position) hide(); else show(); }}
        className="flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-accent-tint hover:text-white">
        <Info size={13} aria-hidden="true" />
      </button>
      {position && (
        <span id={id} role="tooltip" style={{ ...position, width: WIDTH, position: "fixed" }} className="z-[70] rounded-evidence border border-accent-line bg-[#231C42] px-3 py-2 text-left text-xs font-normal normal-case leading-[18px] tracking-normal text-ink shadow-xl shadow-black/50">
          {children}
        </span>
      )}
    </span>
  );
}
