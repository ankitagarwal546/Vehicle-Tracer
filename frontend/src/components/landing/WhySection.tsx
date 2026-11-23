import { Camera, Clock3, Fingerprint, ScanText, SearchX, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const CARDS: { icon: LucideIcon; title: string; problem: string; answer: string; x: string }[] = [
  { icon: ScanText, title: "Plates are rarely whole", problem: "Blur, glare and other vehicles hide characters in almost every frame.", answer: "VITRA combines many frames per character and leaves anything unseen as ?.", x: "29%" },
  { icon: Clock3, title: "Hours lost to scrubbing", problem: "Investigators replay footage again and again to find one vehicle.", answer: "Every vehicle is tracked automatically, so review starts with a list.", x: "68%" },
  { icon: Camera, title: "Cameras do not talk", problem: "The same vehicle appears in separate clips with nothing connecting them.", answer: "VITRA proposes cross-camera links and shows why, for you to confirm.", x: "10%" },
  { icon: ScanText, title: "OCR guesses look like facts", problem: "A confident wrong character can send a case in the wrong direction.", answer: "Each character shows its frames, confidence and rejected reads.", x: "57%" },
  { icon: SearchX, title: "A no-match can mislead", problem: "A registry with the wrong plate format looks like the vehicle does not exist.", answer: "VITRA separates a genuine no-match from no registry coverage.", x: "32%" },
  { icon: Fingerprint, title: "Evidence gets challenged", problem: "If you cannot show how a result was made, it is hard to rely on.", answer: "Hashes, raw crops and an audit log follow every result into the report.", x: "73%" },
];

function WhyCard({ card, floating }: { card: typeof CARDS[number]; floating: boolean }) {
  const Icon = card.icon;
  const [open, setOpen] = useState(false);
  return (
    <article tabIndex={floating ? 0 : undefined} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      className={`group relative flex flex-col rounded-2xl border p-5 transition-all duration-500 ${floating ? "h-[250px] w-[270px]" : ""} ${open ? "border-signal/70 bg-[#2A2545]/95 shadow-[0_0_46px_rgb(246_215_67/0.2)]" : "border-white/12 bg-[#1B1533]/95"}`}>
      <span className={`flex h-9 w-9 items-center justify-center rounded-lg border transition-colors duration-500 ${open ? "border-signal bg-signal text-[#14101F]" : "border-accent-soft/35 bg-accent-tint text-accent-soft"}`}><Icon size={17} aria-hidden="true" /></span>
      <h3 className="mt-auto pt-5 text-[15px] font-semibold leading-5 text-white">{card.title}</h3>
      {floating ? (
        <div className="relative mt-1.5 min-h-[76px] text-[13px] leading-[19px]">
          <p className={`absolute inset-0 text-[#CFCAE6] transition-opacity duration-300 ${open ? "opacity-0" : "opacity-100"}`}>{card.problem}</p>
          <p className={`absolute inset-0 text-white transition-opacity duration-300 ${open ? "opacity-100" : "opacity-0"}`}>{card.answer}</p>
        </div>
      ) : (
        <>
          <p className="mt-1.5 text-[13px] leading-[19px] text-[#CFCAE6]">{card.problem}</p>
          <p className="mt-2 border-t border-white/10 pt-2 text-[13px] leading-[19px] text-white"><span className="font-semibold text-signal">VITRA: </span>{card.answer}</p>
        </>
      )}
    </article>
  );
}

export function WhySection({ animated }: { animated: boolean }) {
  const section = useRef<HTMLElement>(null);
  const items = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (!animated) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const element = section.current;
      if (!element) return;
      const viewport = window.innerHeight;
      const box = element.getBoundingClientRect();
      const travel = Math.max(box.height - viewport, 1);
      const progress = Math.min(Math.max(-box.top / travel, 0), 1);
      const gap = viewport * 0.44;
      const distance = viewport + gap * CARDS.length + 80;
      items.current.forEach((item, index) => {
        if (item) item.style.transform = `translate3d(0, ${viewport * 0.92 + index * gap - progress * distance}px, 0)`;
      });
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

  const heading = (
    <>
      <span className="inline-block rounded-full border border-accent-soft/50 bg-accent-tint/60 px-3 py-1 text-xs font-medium text-accent-soft">Why VITRA Exists</span>
      <h2 id="why-title" className="mt-5 text-4xl font-normal tracking-tight text-white sm:text-5xl lg:text-[64px] lg:leading-[1.06]">CCTV Shows More Than Anyone Can Check</h2>
      <p className="mx-auto mt-5 max-w-2xl text-[15px] leading-6 text-[#CFCAE6] sm:text-base">Cameras record everything, but the answer is buried across hours of footage, partial plates and disconnected clips. VITRA exists to turn that footage into evidence a person can verify.</p>
    </>
  );

  return (
    <section id="why" ref={section} aria-labelledby="why-title" className={animated ? "relative lg:h-[340vh]" : "relative"}>
      {animated && (
        <div className="sticky top-0 hidden h-screen overflow-hidden lg:block">
          <div className="absolute inset-0 flex items-center justify-center px-6"><div className="max-w-4xl text-center">{heading}</div></div>
          {CARDS.map((card, index) => (
            <div key={card.title} ref={(node) => { items.current[index] = node; }} className="absolute top-0 will-change-transform" style={{ left: card.x }}>
              <WhyCard card={card} floating />
            </div>
          ))}
        </div>
      )}
      <div className={`mx-auto max-w-6xl px-4 py-20 sm:px-6 ${animated ? "lg:hidden" : ""}`}>
        <div className="reveal text-center">{heading}</div>
        <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CARDS.map((card) => <div key={card.title} className="reveal"><WhyCard card={card} floating={false} /></div>)}
        </div>
      </div>
    </section>
  );
}
