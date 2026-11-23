import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const SCALES = [0, 2, 4, 8];

export interface SourceContext {
  frame?: string;
  label: string;
}

/** Opens a plate image at true pixels while keeping its source frame and timestamp in view. */
export function ZoomImage({ src, alt, title, detail, compact = false, source }: {
  src?: string;
  alt: string;
  title: string;
  detail?: string;
  compact?: boolean;
  source?: SourceContext;
}) {
  const [open, setOpen] = useState(false);
  const [scale, setScale] = useState(4);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const close = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;
    // A native modal keeps keyboard focus inside and closes on Escape.
    dialog.current?.showModal();
    close.current?.focus();
    const trigger = opener.current;
    return () => trigger?.focus();
  }, [open]);

  if (!src) return null;
  const style = scale && size ? { width: size.width * scale, height: size.height * scale, maxWidth: "none" } : undefined;

  return (
    <>
      <figure className="min-w-0">
        <figcaption className={`mb-0.5 truncate ${compact ? "text-2xs font-medium text-ink" : "label"}`} title={title}>{title}</figcaption>
        <button ref={opener} type="button" aria-label={`Zoom ${title}`} onClick={() => setOpen(true)} className={`block w-full cursor-zoom-in rounded-evidence border border-line bg-slate-100 hover:border-accent ${compact ? "h-12" : "h-28"}`}>
          <img src={src} alt={alt} loading="lazy" className="h-full w-full object-contain [image-rendering:pixelated]" />
        </button>
        {detail && <div className="num mt-0.5 truncate text-2xs text-muted" title={detail}>{detail}</div>}
      </figure>
      {open && (
        <dialog ref={dialog} aria-label={title} onClose={() => setOpen(false)} className="on-shell fixed inset-0 z-50 m-0 h-full max-h-none w-full max-w-none flex-col border-0 bg-shell p-0 text-shell-text open:flex" onClick={() => setOpen(false)}>
          <div className="flex flex-wrap items-center gap-2 border-b border-shell-line px-3 py-2 text-xs" onClick={(event) => event.stopPropagation()}>
            <span className="min-w-0 flex-1"><span className="font-semibold">{title}</span>{detail && <span className="num ml-2 text-shell-muted">{detail}</span>}</span>
            <span className="flex" role="group" aria-label="Zoom level">
              {SCALES.map((value) => (
                <button key={value} type="button" aria-pressed={scale === value} onClick={() => setScale(value)} className={`-ml-px min-h-8 border border-shell-muted/60 px-2.5 py-1 ${scale === value ? "bg-shell-text text-shell" : "hover:bg-shell-raised"}`}>{value ? `${value}×` : "Fit"}</button>
              ))}
            </span>
            <button ref={close} type="button" aria-label="Close zoom" className="min-h-8 px-1.5 hover:bg-shell-raised" onClick={() => setOpen(false)}><X size={16} /></button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <div className="flex min-h-0 min-w-0 flex-1 overflow-auto p-4">
              <img src={src} alt={alt} style={style} onClick={(event) => event.stopPropagation()}
                onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
                className={`m-auto [image-rendering:pixelated] ${scale ? "" : "max-h-full max-w-full min-h-[30vh] object-contain"}`} />
            </div>
            {source && (
              <aside aria-label="Source frame" className="shrink-0 border-t border-shell-line p-3 lg:w-80 lg:border-l lg:border-t-0" onClick={(event) => event.stopPropagation()}>
                <div className="mb-1 text-2xs font-semibold text-shell-muted">Source frame</div>
                {source.frame && <img src={source.frame} alt="Annotated source frame" className="max-h-[22vh] w-full object-contain lg:max-h-none" />}
                <div className="num mt-1 text-2xs">{source.label}</div>
              </aside>
            )}
          </div>
          <p className="border-t border-shell-line px-3 py-1.5 text-2xs text-shell-muted">Zoom enlarges existing pixels. It does not recover detail missing from the footage.</p>
        </dialog>
      )}
    </>
  );
}
