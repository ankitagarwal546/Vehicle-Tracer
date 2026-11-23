import { useEffect, useRef, useState, type ReactNode } from "react";
import { DemoTag, DetectVisual, IngestVisual, MatchVisual, RecoverVisual, ReviewVisual } from "./StepVisuals";

const CORNER = 18;
const DESKTOP = 1024;
const clamp = (value: number, low = 0, high = 1) => Math.min(Math.max(value, low), high);

const STEPS: { step: string; title: string; body: string; visual: (active: boolean, animated: boolean) => ReactNode }[] = [
  { step: "Ingest", title: "Lock the evidence first", body: "Every clip is hashed with SHA-256 on arrival and stored read-only, so the chain of custody starts before any analysis does.", visual: (active) => <IngestVisual active={active} /> },
  { step: "Detect", title: "Follow every vehicle", body: "VITRA detects and tracks each vehicle across the clip, merges broken tracks, and grades how reliable each one is.", visual: (_active, animated) => <DetectVisual animated={animated} /> },
  { step: "Recover", title: "Rebuild the plate, frame by frame", body: "No single frame shows the whole plate. VITRA compares every read per character, and anything the footage never showed stays unknown.", visual: (active) => <RecoverVisual active={active} /> },
  { step: "Match", title: "Search only what can be searched", body: "Readable plates are compared with compatible registry records. You see a candidate, a reasoned no-match, or a clear warning that the registry cannot cover this format.", visual: (active) => <MatchVisual active={active} /> },
  { step: "Review", title: "A person makes the call", body: "Investigators inspect the evidence, confirm or reject cross-camera links, and export a report with hashes and a full audit log.", visual: (active) => <ReviewVisual active={active} /> },
];

interface Geometry { d: string; ys: number[]; lengths: number[]; arrivals: number[]; total: number }

export function HowItWorks({ animated }: { animated: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const cards = useRef<(HTMLElement | null)[]>([]);
  const base = useRef<SVGPathElement>(null);
  const glow = useRef<SVGPathElement>(null);
  const trace = useRef<SVGPathElement>(null);
  const head = useRef<SVGCircleElement>(null);
  const halo = useRef<SVGCircleElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [lit, setLit] = useState(animated ? 0 : STEPS.length);

  useEffect(() => {
    const container = root.current;
    const line = trace.current;
    if (!container || !line || !base.current || !glow.current || !svg.current) return;
    const probe = document.createElementNS("http://www.w3.org/2000/svg", "path");
    let geometry: Geometry = { d: "", ys: [], lengths: [], arrivals: [], total: 0 };
    let current = animated ? 0 : Number.MAX_SAFE_INTEGER;
    let target = 0;
    let raf = 0;
    let shown = animated ? 0 : STEPS.length;

    const lengthOf = (d: string) => {
      probe.setAttribute("d", d);
      return probe.getTotalLength();
    };

    const measure = () => {
      const origin = container.getBoundingClientRect();
      const width = container.clientWidth;
      const height = container.clientHeight;
      svg.current!.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const boxes = cards.current.filter(Boolean).map((card) => {
        const box = card!.getBoundingClientRect();
        return { left: box.left - origin.left, right: box.right - origin.left, top: box.top - origin.top, bottom: box.bottom - origin.top };
      });
      if (!boxes.length) return;
      const ys: number[] = [];
      const lengths: number[] = [];
      const arrivals: number[] = [0];
      let d: string;
      if (width >= DESKTOP) {
        const exitY = (box: typeof boxes[number]) => box.top + Math.min((box.bottom - box.top) * 0.36, 190);
        d = "";
        boxes.slice(0, -1).forEach((box, index) => {
          const next = boxes[index + 1];
          const toRight = (next.left + next.right) / 2 > (box.left + box.right) / 2;
          const startX = toRight ? box.right - 2 : box.left + 2;
          const y = exitY(box);
          const x = (next.left + next.right) / 2;
          const dir = toRight ? 1 : -1;
          if (!d) d = `M${startX} ${y}`;
          else d += ` L${startX} ${y}`;
          ys.push(y);
          lengths.push(lengthOf(d));
          d += ` H${x - dir * CORNER} Q${x} ${y} ${x} ${y + CORNER} V${next.top + 2}`;
          ys.push(next.top + 2);
          const arrived = lengthOf(d);
          lengths.push(arrived);
          arrivals.push(arrived);
        });
      } else {
        const x = 11;
        d = `M${x} ${boxes[0].top + 14}`;
        ys.push(boxes[0].top + 14);
        lengths.push(0);
        boxes.slice(1).forEach((box) => {
          d += ` V${box.top + 14}`;
          ys.push(box.top + 14);
          const arrived = lengthOf(d);
          lengths.push(arrived);
          arrivals.push(arrived);
        });
      }
      const total = lengthOf(d);
      geometry = { d, ys, lengths, arrivals, total };
      [base.current!, glow.current!, line].forEach((path) => {
        path.setAttribute("d", d);
        path.style.strokeDasharray = `${total} ${total}`;
      });
      base.current!.style.strokeDasharray = "none";
      computeTarget();
      paint(true);
    };

    const computeTarget = () => {
      const { ys, lengths, total } = geometry;
      if (!ys.length) return;
      const focus = window.innerHeight * 0.62 - container.getBoundingClientRect().top;
      if (focus <= ys[0]) target = lengths[0];
      else if (focus >= ys[ys.length - 1]) target = total;
      else {
        let index = 0;
        while (index < ys.length - 2 && focus > ys[index + 1]) index += 1;
        const span = ys[index + 1] - ys[index] || 1;
        target = lengths[index] + (lengths[index + 1] - lengths[index]) * clamp((focus - ys[index]) / span);
      }
      if (!animated) target = total;
    };

    const paint = (force = false) => {
      const { total, arrivals } = geometry;
      if (!total) return;
      current = force && !animated ? total : Math.min(current, total);
      const offset = Math.max(total - current, 0);
      line.style.strokeDashoffset = String(offset);
      glow.current!.style.strokeDashoffset = String(offset);
      const point = line.getPointAtLength(current);
      [head.current!, halo.current!].forEach((dot) => {
        dot.setAttribute("cx", String(point.x));
        dot.setAttribute("cy", String(point.y));
      });
      const inView = container.getBoundingClientRect().top < window.innerHeight * 0.74;
      const next = !animated ? STEPS.length : inView ? arrivals.filter((value) => current >= value - 2).length : 0;
      if (next !== shown) {
        shown = next;
        setLit(next);
      }
    };

    let previous = 0;
    const frame = (now: number) => {
      raf = 0;
      const elapsed = previous ? Math.min(now - previous, 1000) : 16;
      previous = now;
      const distance = target - current;
      // Time-based easing keeps the trace close to the scroll position on slower machines.
      current += Math.abs(distance) < 0.6 ? distance : distance * (1 - Math.exp(-elapsed / 70));
      paint();
      if (Math.abs(target - current) > 0.5) raf = requestAnimationFrame(frame);
      else previous = 0;
    };
    const onScroll = () => {
      computeTarget();
      if (!raf) raf = requestAnimationFrame(frame);
    };

    const observer = new ResizeObserver(measure);
    observer.observe(container);
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    onScroll();
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [animated]);

  return (
    <section id="how" aria-labelledby="how-title" className="relative isolate bg-[#0E0A1E] pb-24 pt-20 lg:pb-36 lg:pt-28">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-clip">
        <div className="sticky top-0 h-screen overflow-hidden">
          <div className="aurora-a absolute -right-[12%] top-[16%] h-[78vh] w-[46vw] bg-[radial-gradient(closest-side,rgb(124_140_240/0.34),transparent)]" />
          <div className="aurora-b absolute -right-[8%] top-[34%] h-[60vh] w-[32vw] bg-[radial-gradient(closest-side,rgb(242_231_255/0.3),transparent)]" />
          <div className="aurora-b absolute -left-[16%] bottom-[2%] h-[72vh] w-[46vw] bg-[radial-gradient(closest-side,rgb(95_61_196/0.32),transparent)]" />
        </div>
      </div>
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <h2 id="how-title" className="reveal text-center text-4xl font-normal tracking-tight text-white sm:text-6xl lg:text-7xl">How It Works</h2>
        <p className="reveal mx-auto mt-4 max-w-xl text-center text-[15px] text-[#CFCAE6] sm:text-base">Five stages take a raw clip to a report you can defend. Scroll to follow the trace.</p>
        <div ref={root} className="relative mt-14 lg:mt-20">
          <svg ref={svg} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
            <path ref={base} fill="none" stroke="rgb(255 255 255 / 0.16)" strokeWidth="2" />
            <path ref={glow} fill="none" stroke="#F6D743" strokeOpacity="0.2" strokeWidth="8" strokeLinecap="round" />
            <path ref={trace} fill="none" stroke="#F6D743" strokeWidth="2.5" />
            <circle ref={halo} r="11" fill="#F6D743" fillOpacity="0.28" />
            <circle ref={head} r="5" fill="#F6D743" />
          </svg>
          <ol className="relative space-y-16 pl-7 lg:space-y-28 lg:pl-0">
            {STEPS.map((item, index) => {
              const active = index < lit;
              return (
                <li key={item.step} className={`lg:flex ${index % 2 ? "lg:justify-end" : "lg:justify-start"}`}>
                  <article ref={(node) => { cards.current[index] = node; }} aria-labelledby={`step-${index}`}
                    className={`w-full rounded-[22px] border bg-[#120D28] p-5 transition-all duration-700 sm:p-7 lg:w-[54%] ${active ? "translate-y-0 border-accent-soft/45 shadow-2xl shadow-[#3B2A96]/30" : "translate-y-5 border-white/10"}`}>
                    <div className={`transition-opacity duration-700 ${active ? "opacity-100" : "opacity-45"}`}>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-signal"><span className="num mr-1.5">{String(index + 1).padStart(2, "0")}</span>{item.step}</span>
                      {index !== 1 && <DemoTag />}
                    </div>
                    <h3 id={`step-${index}`} className="text-2xl font-normal tracking-tight text-white sm:text-[28px] sm:leading-9">{item.title}</h3>
                    <p className="mb-5 mt-2 text-[15px] leading-6 text-[#BDB7D6]">{item.body}</p>
                    {item.visual(active, animated)}
                    </div>
                  </article>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}
