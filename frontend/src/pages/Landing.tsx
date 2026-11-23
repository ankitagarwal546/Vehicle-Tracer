import { ArrowRight, ArrowUpRight, Building2, Camera, Check, ChevronDown, FileText, Gavel, Menu, ScanSearch, Shield, Share2, TrafficCone, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { HowItWorks } from "../components/landing/HowItWorks";
import { WhySection } from "../components/landing/WhySection";
import { FULL_NAME, Logo, LogoMark } from "../components/Logo";
import { OpeningScene } from "../components/OpeningScene";
import type { CaseSummary, Health } from "../types";

const EXIT_MS = 380;
const NAV = [["why", "Why VITRA"], ["achieve", "Results"], ["how", "How It Works"], ["who", "Who It's For"], ["faq", "FAQ"]];
const STACK = ["YOLOv8 detection", "ByteTrack tracking", "FastALPR plate OCR", "OpenCLIP attributes", "Multi-frame fusion", "SHA-256 custody", "Explainable matching", "HTML and PDF reports"];
const READS = ["DE?O4??2", "?EMO??72", "D?M?4?7?"];
const FAQS = [
  ["What does VITRA do?", "VITRA analyses CCTV clips, tracks each vehicle, recovers plate characters across frames, compares readable plates with a registry, and shows the evidence behind every result."],
  ["Does it identify a vehicle or its owner for certain?", "No. VITRA produces investigative leads. A person must verify any result independently before relying on it."],
  ["What happens when a character cannot be read?", "It stays as ?. VITRA never fills a character from plate patterns, registry records or vehicle attributes."],
  ["What is the difference between no match and no coverage?", "No match means a compatible registry was searched and nothing agreed. No coverage means the registry has no records in that plate format, so no real search was possible."],
  ["Is the match score a probability?", "No. It is an uncalibrated ranking value used to order candidates. It should not be read as the chance that a match is correct."],
  ["Can enhancement recover a plate the camera missed?", "No. Enhanced views can make existing pixels easier to inspect, but they cannot create detail that is absent from the footage."],
  ["Is the included registry real?", "No. The default registry is synthetic test data with fictional plates and people. Upload your own registry to search real records."],
];
const WHO = [
  { icon: Gavel, text: "Investigators building vehicle timelines" },
  { icon: TrafficCone, text: "Traffic control and enforcement rooms" },
  { icon: Building2, text: "Campus, port and site security teams" },
  { icon: Shield, text: "Forensic analysts preparing evidence reports" },
];
const USE_CASES = [
  { icon: ScanSearch, title: "Recover a partial plate from difficult footage" },
  { icon: Share2, title: "Trace one vehicle across several cameras" },
  { icon: FileText, title: "Produce a report that shows its evidence" },
];
const BEFORE = ["Replay footage", "Note plate by hand", "Search the registry"];
const AFTER = ["Vehicles tracked", "Plate fused", "Registry compared"];

const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function useReveal(root: React.RefObject<HTMLElement>) {
  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    element.querySelectorAll(".reveal").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [root]);
}

function Counter({ value, decimals = 0, suffix = "", animated }: { value: number; decimals?: number; suffix?: string; animated: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(animated ? 0 : value);
  useEffect(() => {
    if (!animated || !ref.current) return;
    let raf = 0;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const start = performance.now();
      const step = (now: number) => {
        const t = Math.min((now - start) / 1400, 1);
        setShown(value * (1 - (1 - t) ** 3));
        if (t < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, { threshold: 0.4 });
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [animated, value]);
  return <span ref={ref} className="tabular-nums">{shown.toFixed(decimals)}<span className="text-[#9C8CFF]">{suffix}</span></span>;
}

function HeroConsole({ cases, casesReady, health, animated }: { cases: CaseSummary[]; casesReady: boolean; health: Health | null; animated: boolean }) {
  const frame = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(animated ? 0 : 8);

  useEffect(() => {
    if (!animated) return;
    const timer = window.setInterval(() => setStep((value) => (value + 1) % 11), 800);
    return () => window.clearInterval(timer);
  }, [animated]);

  useEffect(() => {
    if (!animated) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const element = frame.current;
      if (!element) return;
      const t = Math.min(window.scrollY / (window.innerHeight * 0.72), 1);
      element.style.transform = `perspective(1500px) rotateX(${(1 - t) * 15}deg) scale(${0.9 + t * 0.1}) translateY(${(1 - t) * 18}px)`;
    };
    const request = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", request, { passive: true });
    window.addEventListener("resize", request);
    return () => {
      window.removeEventListener("scroll", request);
      window.removeEventListener("resize", request);
      cancelAnimationFrame(raf);
    };
  }, [animated]);

  const clips = cases.reduce((total, item) => total + item.clip_count, 0);
  const tracks = cases.reduce((total, item) => total + item.vehicle_count, 0);
  const stats = [
    ["Investigations", casesReady ? cases.length : "–"],
    ["CCTV clips", casesReady ? clips : "–"],
    ["Vehicle tracks", casesReady ? tracks.toLocaleString() : "–"],
    ["Registry records", health ? health.registry_count.toLocaleString() : "–"],
  ];
  const fused = step < 4 ? 0 : Math.min((step - 3) * 2, 8);

  return (
    <div ref={frame} className="opening-rise mx-auto max-w-6xl origin-top rounded-2xl border border-white/15 bg-[#120D26] p-2 shadow-[0_30px_120px_rgb(83_60_210/0.38)] will-change-transform sm:p-3" style={{ animationDelay: "620ms" }}>
      <div className="mb-2 flex items-center justify-between gap-2 px-1.5 py-1">
        <span className="flex items-center gap-2 text-xs font-semibold text-white"><LogoMark size={18} />Investigation overview</span>
        <span className="text-[10px] text-[#BDB7D6]">Counts are live. The scene is illustrative.</span>
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2">
            <div className="num text-lg font-semibold text-white sm:text-2xl">{value}</div>
            <div className="text-[10px] text-[#BDB7D6] sm:text-[11px]">{label}</div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 grid gap-1.5 md:grid-cols-[minmax(0,1.75fr)_minmax(250px,1fr)]">
        <div className="relative h-52 overflow-hidden rounded-lg border border-white/10 bg-[#0D0F15] sm:h-80">
          <OpeningScene animated={animated} embedded />
          <div className="scene-lines absolute inset-0" />
          <span className="absolute left-2 top-2 rounded border border-white/20 bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">Illustrative scene</span>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
          <div className="mb-2 flex items-baseline justify-between"><span className="text-xs font-semibold text-white">Plate recovery</span><span className="text-[10px] text-[#BDB7D6]">Demo plate</span></div>
          <div className="space-y-1">
            {READS.map((text, row) => (
              <div key={text} className={`grid grid-cols-8 gap-0.5 transition-opacity duration-300 ${step > row ? "opacity-100" : "opacity-0"}`}>
                {[...text].map((char, index) => <span key={index} className={`num flex h-6 items-center justify-center rounded text-[10px] font-semibold ${char === "?" ? "bg-white/[0.04] text-[#8F89AD]" : "bg-white/15 text-white"}`}>{char}</span>)}
              </div>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-8 gap-0.5 border-t border-white/10 pt-2">
            {[..."DEMO4?72"].map((char, index) => <span key={index} className={`num flex h-8 items-center justify-center rounded text-xs font-semibold transition-all duration-300 ${index >= fused ? "bg-white/[0.04] text-transparent" : char === "?" ? "border border-dashed border-signal text-signal" : "bg-[#F4F1FF] text-[#14101F]"}`}>{char}</span>)}
          </div>
          <p className={`mt-2 text-[11px] leading-4 text-[#CFCAE6] transition-opacity duration-300 ${fused === 8 ? "opacity-100" : "opacity-0"}`}>Slot 6 was never visible, so it stays <span className="num font-semibold text-signal">?</span></p>
        </div>
      </div>
    </div>
  );
}

function BeforeAfter() {
  const [mode, setMode] = useState<"before" | "after">("after");
  const after = mode === "after";
  return (
    <section aria-labelledby="simple-title" className="relative overflow-hidden px-4 py-20 sm:px-6 lg:py-28">
      <div className="mx-auto max-w-6xl text-center">
        <h2 id="simple-title" className="reveal text-4xl font-normal tracking-tight text-white sm:text-6xl">Simple, Fast,<br /><span className="text-signal">Explainable</span></h2>
        <p className="reveal mx-auto mt-4 max-w-xl text-[15px] text-[#CFCAE6] sm:text-base">Replace camera-by-camera checking with one evidence workflow.</p>
        <div role="group" aria-label="Compare workflow" className="reveal mt-6 inline-flex gap-1 rounded-lg border border-white/15 p-1">
          {([["before", "Before VITRA"], ["after", "With VITRA"]] as const).map(([key, label]) => (
            <button key={key} aria-pressed={mode === key} onClick={() => setMode(key)} className={`min-h-9 rounded-md px-4 text-xs font-semibold transition-colors ${mode === key ? "bg-white text-[#14101F]" : "text-[#CFCAE6] hover:text-white"}`}>{label}</button>
          ))}
        </div>
        <div className="reveal mt-8 rounded-2xl border border-white/12 bg-[#171130] p-3 sm:p-5">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            {["North gate", "Ring road", "Toll plaza", "Depot exit", "Car park"].map((camera, index) => (
              <div key={camera} className={`rounded-xl border border-white/10 bg-white/[0.035] p-3 text-left ${index === 4 ? "col-span-2 md:col-span-1" : ""}`}>
                <div className="mb-2.5 flex items-center justify-between gap-1 text-xs font-semibold text-white"><span className="truncate">{camera}</span><Camera size={14} aria-hidden="true" className="shrink-0 text-accent-soft" /></div>
                <ul className="space-y-1.5">
                  {(after ? AFTER : BEFORE).map((item, row) => (
                    <li key={item} className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-all duration-500 ${after ? "border-emerald-300/60 bg-emerald-50 text-emerald-900" : "border-white/12 bg-white/[0.03] text-[#CFCAE6]"}`} style={{ transitionDelay: `${index * 45 + row * 70}ms` }}>
                      {after ? <Check size={12} aria-hidden="true" className="shrink-0" /> : <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#8F89AD]" />}<span className="truncate">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className={`mt-2 rounded-xl border px-4 py-3 text-sm font-medium transition-colors duration-500 ${after ? "border-signal/50 bg-signal/10 text-white" : "border-white/10 bg-white/[0.03] text-[#CFCAE6]"}`}>
            {after ? "One shortlist, cross-camera links for review, and a report with its evidence attached." : "Separate notes per camera, with connections held in someone's head."}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Landing({ cases, casesReady, health, onEnter }: {
  cases: CaseSummary[];
  casesReady: boolean;
  health: Health | null;
  onEnter: () => void;
}) {
  const [animated] = useState(() => !prefersReducedMotion());
  const [leaving, setLeaving] = useState(false);
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const exit = useRef<number>();
  useReveal(root);

  const enter = useCallback(() => {
    if (exit.current !== undefined) return;
    if (!animated) {
      onEnter();
      return;
    }
    setLeaving(true);
    exit.current = window.setTimeout(onEnter, EXIT_MS);
  }, [animated, onEnter]);

  useEffect(() => () => window.clearTimeout(exit.current), []);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    const onScroll = () => setScrolled(window.scrollY > 16);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const jump = (id: string) => {
    setMenu(false);
    document.getElementById(id)?.scrollIntoView({ behavior: animated ? "smooth" : "auto", block: "start" });
  };
  const year = new Date().getFullYear();
  const primary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-accent px-5 text-sm font-semibold text-white transition-colors hover:bg-accent-dark";
  const light = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-[#ECEAF7] px-5 text-sm font-semibold text-[#14101F] transition-colors hover:bg-white";

  return (
    <div ref={root} className={`on-shell relative min-h-screen overflow-x-clip bg-[#0B0818] text-shell-text ${leaving ? "opening-exit" : ""}`}>
      <header className={`fixed inset-x-0 top-0 z-40 transition-colors duration-300 ${scrolled || menu ? "bg-[#0B0818]/95" : ""}`}>
        <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <a href="#/" aria-label="VITRA home" onClick={(event) => { event.preventDefault(); window.scrollTo({ top: 0, behavior: animated ? "smooth" : "auto" }); }} className="rounded-lg"><Logo size={30} /></a>
          <nav aria-label="Page sections" className="hidden items-center gap-0.5 rounded-full border border-white/12 bg-white/[0.045] px-1.5 py-1 lg:flex">
            {NAV.map(([id, label]) => <button key={id} onClick={() => jump(id)} className="min-h-8 rounded-full px-3.5 text-[13px] text-[#DAD6EC] transition-colors hover:bg-white/10 hover:text-white">{label}</button>)}
          </nav>
          <div className="flex items-center gap-2">
            <button onClick={enter} className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[#ECEAF7] px-4 text-[13px] font-semibold text-[#14101F] transition-colors hover:bg-white">Open dashboard</button>
            <button aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu} onClick={() => setMenu(!menu)} className="flex h-10 w-10 items-center justify-center rounded-full border border-white/15 lg:hidden">{menu ? <X size={18} /> : <Menu size={18} />}</button>
          </div>
        </div>
        {menu && (
          <nav aria-label="Page sections" className="grid gap-1 border-t border-white/10 px-4 pb-3 pt-2 lg:hidden">
            {NAV.map(([id, label]) => <button key={id} onClick={() => jump(id)} className="min-h-10 rounded-lg px-3 text-left text-sm text-[#ECEAF7] hover:bg-white/10">{label}</button>)}
          </nav>
        )}
      </header>

      <main>
        <section aria-labelledby="hero-title" className="relative isolate overflow-hidden px-4 pb-14 pt-28 sm:px-6 lg:pb-20 lg:pt-36">
          <div aria-hidden="true" className="absolute inset-0 -z-10">
            <div className="aurora-a absolute left-[8%] top-[-8%] h-[84vh] w-[62vw] bg-[radial-gradient(closest-side,rgb(74_47_189/0.5),transparent)]" />
            <div className="aurora-b absolute right-[2%] top-[14%] h-[72vh] w-[50vw] bg-[radial-gradient(closest-side,rgb(45_62_158/0.42),transparent)]" />
          </div>
          <div className="mx-auto max-w-4xl text-center">
            <p className="opening-rise mb-5 inline-flex rounded-full border border-accent-soft/50 bg-accent-tint/60 px-3.5 py-1.5 text-xs font-medium text-accent-soft"><span className="mr-2 font-semibold tracking-[0.1em] text-white">VITRA</span>{FULL_NAME}</p>
            <h1 id="hero-title" className="opening-rise text-[40px] font-normal leading-[1.08] tracking-[-0.025em] text-white sm:text-6xl lg:text-[68px]" style={{ animationDelay: "100ms" }}>Vehicle Intelligence for CCTV Investigations</h1>
            <p className="opening-rise mx-auto mt-5 max-w-2xl text-[15px] leading-6 text-[#D6D2E8] sm:text-[17px] sm:leading-7" style={{ animationDelay: "260ms" }}>VITRA tracks vehicles through your footage, recovers partial number plates across frames, and shows the evidence behind every result. What the camera never saw stays unknown.</p>
            <div className="opening-rise mt-7 flex flex-wrap justify-center gap-3" style={{ animationDelay: "400ms" }}>
              <button onClick={enter} className={primary}>Open dashboard <ArrowRight size={16} aria-hidden="true" /></button>
              <button onClick={() => jump("how")} className={light}>See How It Works</button>
            </div>
          </div>
          <div className="mt-12 lg:mt-16"><HeroConsole cases={cases} casesReady={casesReady} health={health} animated={animated} /></div>
        </section>

        <section aria-label="Technology" className="border-y border-white/10 py-6">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-4 sm:px-6">
            <p className="hidden max-w-[150px] shrink-0 text-sm font-medium leading-5 text-white md:block">Built on a proven vision stack</p>
            <div className="min-w-0 flex-1 overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_10%,black_90%,transparent)]">
              <ul className="marquee-track flex w-max gap-10">
                {[...STACK, ...STACK].map((item, index) => <li key={index} aria-hidden={index >= STACK.length} className="whitespace-nowrap text-[15px] font-medium text-[#BDB7D6]">{item}</li>)}
              </ul>
            </div>
          </div>
        </section>

        <WhySection animated={animated} />

        <section id="achieve" aria-labelledby="achieve-title" className="scroll-mt-20 px-4 py-20 sm:px-6 lg:py-28">
          <div className="mx-auto max-w-6xl">
            <span className="reveal inline-block rounded-full border border-accent-soft/50 bg-accent-tint/60 px-3 py-1 text-xs font-medium text-accent-soft">What You Can Achieve</span>
            <h2 id="achieve-title" className="reveal mt-4 max-w-3xl text-4xl font-normal tracking-tight text-white sm:text-5xl">Faster answers, with the evidence still attached</h2>
            <div className="mt-8 grid gap-3 md:grid-cols-2">
              <article className="reveal flex min-h-[340px] flex-col rounded-2xl border border-white/12 bg-[#171130] p-6 md:row-span-2">
                <h3 className="text-[15px] text-white">Analyse a 60-second 4K clip in</h3>
                <div className="mt-2 text-7xl font-extralight tracking-tight text-[#E8E5F7] sm:text-8xl"><Counter value={84} suffix="s" animated={animated} /></div>
                <p className="mt-auto pt-6 text-sm leading-5 text-[#CFCAE6]">Down from 164 seconds before this release, measured on one real traffic clip on a local Mac, with every track still analysed.</p>
              </article>
              <article className="reveal rounded-2xl border border-white/12 bg-[#171130] p-6">
                <h3 className="text-[15px] text-white">Find the right vehicle in the top five</h3>
                <div className="mt-2 text-6xl font-extralight tracking-tight text-[#E8E5F7] sm:text-7xl"><Counter value={97.8} decimals={1} suffix="%" animated={animated} /></div>
                <p className="mt-3 text-sm leading-5 text-[#CFCAE6]">Top-5 recall across 46 rankable cases in the labelled synthetic evaluation.</p>
              </article>
              <article className="reveal rounded-2xl border border-white/12 bg-[#171130] p-6">
                <h3 className="text-[15px] text-white">Wrong vehicles promoted as candidates</h3>
                <div className="mt-2 text-6xl font-extralight tracking-tight text-[#E8E5F7] sm:text-7xl"><Counter value={0} animated={animated} /><span className="ml-3 text-2xl text-[#9C8CFF]">of 32</span></div>
                <p className="mt-3 text-sm leading-5 text-[#CFCAE6]">When evidence is weak, VITRA says so instead of forcing a match.</p>
              </article>
            </div>
            <p className="reveal mt-4 text-xs leading-5 text-[#BDB7D6]">Results come from this project's own test clip and labelled synthetic test set. They are not a real-world accuracy claim.</p>
          </div>
        </section>

        <HowItWorks animated={animated} />

        <section id="who" aria-labelledby="who-title" className="scroll-mt-20 px-4 py-20 sm:px-6 lg:py-28">
          <div className="mx-auto grid max-w-5xl gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
            <div className="reveal">
              <span className="inline-block rounded-full border border-accent-soft/50 bg-accent-tint/60 px-3 py-1 text-xs font-medium text-accent-soft">Who VITRA Is For</span>
              <h2 id="who-title" className="mt-4 text-2xl font-normal leading-8 text-white">Teams who must explain what the footage shows</h2>
            </div>
            <ul className="divide-y divide-white/10">
              {WHO.map(({ icon: Icon, text }) => (
                <li key={text} className="reveal flex items-center gap-4 py-4 text-lg text-white sm:text-xl">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-soft/35 bg-accent-tint text-accent-soft"><Icon size={17} aria-hidden="true" /></span>{text}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <BeforeAfter />

        <section aria-labelledby="use-title" className="px-4 pb-20 sm:px-6">
          <div className="mx-auto max-w-6xl">
            <h2 id="use-title" className="reveal text-2xl font-normal text-white sm:text-3xl">What you can do first</h2>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              {USE_CASES.map(({ icon: Icon, title }) => (
                <button key={title} onClick={enter} className="reveal group flex min-h-[190px] flex-col rounded-2xl border border-white/12 bg-[#171130] p-5 text-left transition-colors hover:border-accent-soft/60 hover:bg-[#1E1740]">
                  <span className="flex w-full items-start justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent-soft/35 bg-accent-tint text-accent-soft"><Icon size={17} aria-hidden="true" /></span>
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-white transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"><ArrowUpRight size={17} aria-hidden="true" /></span>
                  </span>
                  <span className="mt-auto pt-5 text-lg leading-6 text-white">{title}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" aria-labelledby="faq-title" className="scroll-mt-20 px-4 py-16 sm:px-6 lg:py-24">
          <div className="mx-auto max-w-3xl">
            <h2 id="faq-title" className="reveal text-center text-3xl font-normal tracking-tight text-white sm:text-4xl">Frequently asked questions</h2>
            <div className="reveal mt-8 divide-y divide-white/12 border-y border-white/12">
              {FAQS.map(([question, answer]) => (
                <details key={question} className="group">
                  <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-4 py-3 text-[15px] text-white [&::-webkit-details-marker]:hidden">{question}<ChevronDown size={17} aria-hidden="true" className="shrink-0 text-accent-soft transition-transform group-open:rotate-180" /></summary>
                  <p className="pb-4 pr-8 text-sm leading-6 text-[#CFCAE6]">{answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section aria-labelledby="cta-title" className="relative isolate overflow-hidden px-4 py-24 text-center sm:px-6">
          <div aria-hidden="true" className="absolute inset-0 -z-10">
            <div className="aurora-a absolute left-1/2 top-1/2 h-[70vh] w-[76vw] -translate-x-1/2 -translate-y-1/2 bg-[radial-gradient(closest-side,rgb(74_47_189/0.42),transparent)]" />
          </div>
          <h2 id="cta-title" className="reveal text-4xl font-normal tracking-tight text-white sm:text-6xl">Put VITRA on your footage</h2>
          <p className="reveal mx-auto mt-4 max-w-lg text-[15px] text-[#D6D2E8] sm:text-base">Start an investigation, add a clip, and see what the evidence supports.</p>
          <button onClick={enter} className={`${primary} reveal mt-7`}>Open dashboard <ArrowRight size={16} aria-hidden="true" /></button>
        </section>
      </main>

      <footer className="px-4 pb-6 sm:px-6">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/12 bg-[#120D26] p-6">
          <div>
            <Logo size={34} tagline taglineClassName="!max-w-none" />
            <p className="mt-2 max-w-sm text-xs leading-5 text-[#BDB7D6]">Results are investigative leads and must be verified independently.</p>
          </div>
          <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-1">
            {NAV.map(([id, label]) => <button key={id} onClick={() => jump(id)} className="min-h-8 text-[13px] text-[#CFCAE6] hover:text-white">{label}</button>)}
          </nav>
          <p className="w-full border-t border-white/10 pt-3 text-xs text-[#BDB7D6]">© {year} VITRA</p>
        </div>
      </footer>
    </div>
  );
}
