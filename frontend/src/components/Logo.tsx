import { useId } from "react";

const V_PATH = "M7 8L20 33L33 8";
const CONE_PATH = `${V_PATH}Z`;

export const FULL_NAME = "Vehicle Identification & Trace Analytics";

/** VITRA mark: a V formed by a camera's field of view, with a scan line and a tracking dot. */
export function LogoMark({ size = 28 }: { size?: number }) {
  const clip = `vitra-cone-${useId().replace(/:/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true" className="shrink-0">
      <defs><clipPath id={clip}><path d={CONE_PATH} /></clipPath></defs>
      <path d={CONE_PATH} fill="#6A53E6" fillOpacity="0.36" />
      <g clipPath={`url(#${clip})`}><rect className="logo-scan" x="5" y="7" width="30" height="2.2" fill="#F6D743" fillOpacity="0.9" /></g>
      <path d={V_PATH} pathLength={100} className="logo-draw" stroke="#ECEAF7" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="20" cy="33" r="3.1" fill="#0C0919" stroke="#ECEAF7" strokeWidth="1.8" />
      <path d={V_PATH} pathLength={100} className="logo-signal" stroke="#F6D743" strokeWidth="6.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ size = 28, tagline = false, taglineClassName = "" }: { size?: number; tagline?: boolean; taglineClassName?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark size={size} />
      <span className="min-w-0">
        <span className="block font-semibold leading-none tracking-[0.13em] text-white" style={{ fontSize: Math.round(size * 0.64) }}>VITRA</span>
        {tagline && <span className={`mt-1 block max-w-[158px] text-[9.5px] leading-3 text-shell-muted ${taglineClassName}`}>{FULL_NAME}</span>}
      </span>
    </span>
  );
}
