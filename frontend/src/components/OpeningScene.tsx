import { useEffect, useRef, type RefObject } from "react";

/** An illustrative CCTV view drawn in code. It contains no footage and no case data. */

const TAU = Math.PI * 2;
const CAMERA_HEIGHT = 3.2;
const NEAR_EDGE_Z = 4.2;
const Z_NEAR = 3.3;
const Z_FAR = 62;
const BOX_RANGE = 31;
const ROAD_HALF = 7.6;
const VIOLET = "#B7AEF5";
const TARGET_LANE = 2;

const LANES = [
  { x: -5.5, dir: -1, speed: 3.1, count: 5, offset: 2 },
  { x: -2, dir: -1, speed: 4, count: 4, offset: 9 },
  { x: 2, dir: 1, speed: 3.3, count: 5, offset: 0 },
  { x: 5.5, dir: 1, speed: 2.5, count: 5, offset: 6 },
];
const PAINTS = ["#AEB3C0", "#DADDE5", "#3C404E", "#2D3C60", "#6E2C38", "#536579", "#A99C84", "#23252F"];
const KINDS = [
  { name: "car", w: 1.85, h: 1.42, box: false },
  { name: "suv", w: 1.98, h: 1.72, box: false },
  { name: "car", w: 1.8, h: 1.38, box: false },
  { name: "van", w: 2.05, h: 2.15, box: true },
  { name: "car", w: 1.86, h: 1.45, box: false },
  { name: "truck", w: 2.5, h: 3.25, box: true },
];

interface Vehicle { id: number; lane: number; z: number; kind: number; paint: string }
interface Frame { w: number; h: number; vx: number; vy: number; f: number }
interface Drawn { vehicle: Vehicle; x: number; y: number; bw: number; bh: number; plate: [number, number, number, number]; alpha: number }

const project = (frame: Frame, x: number, z: number, height = 0) => {
  const s = frame.f / z;
  return { x: frame.vx + x * s, y: frame.vy + (CAMERA_HEIGHT - height) * s, s };
};
const clamp = (value: number, low = 0, high = 1) => Math.min(Math.max(value, low), high);

function createVehicles() {
  const list: Vehicle[] = [];
  let id = 3;
  LANES.forEach((lane, laneIndex) => {
    const span = (Z_FAR - Z_NEAR) / lane.count;
    for (let index = 0; index < lane.count; index += 1) {
      list.push({
        id, lane: laneIndex, z: Z_NEAR + ((index * span + lane.offset) % (Z_FAR - Z_NEAR)),
        kind: (id * 7 + laneIndex) % KINDS.length, paint: PAINTS[(id * 5) % PAINTS.length],
      });
      id += laneIndex % 2 ? 3 : 2;
    }
  });
  return list;
}

function glowSprite(colour: string) {
  const sprite = document.createElement("canvas");
  sprite.width = sprite.height = 128;
  const ctx = sprite.getContext("2d")!;
  const gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, colour);
  gradient.addColorStop(0.25, colour.replace("1)", "0.35)"));
  gradient.addColorStop(1, colour.replace("1)", "0)"));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  return sprite;
}

function quad(ctx: CanvasRenderingContext2D, frame: Frame, x1: number, x2: number, z1: number, z2: number) {
  const a = project(frame, x1, z1);
  const b = project(frame, x2, z1);
  const c = project(frame, x2, z2);
  const d = project(frame, x1, z2);
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.lineTo(c.x, c.y);
  ctx.lineTo(d.x, d.y);
  ctx.closePath();
  ctx.fill();
}

function paintBackground(frame: Frame, dpr: number, warm: HTMLCanvasElement) {
  const layer = document.createElement("canvas");
  layer.width = Math.ceil(frame.w * dpr);
  layer.height = Math.ceil(frame.h * dpr);
  const ctx = layer.getContext("2d")!;
  ctx.scale(dpr, dpr);
  const { w, h, vy } = frame;

  const sky = ctx.createLinearGradient(0, 0, 0, vy + 6);
  sky.addColorStop(0, "#11131C");
  sky.addColorStop(0.62, "#1D1D33");
  sky.addColorStop(1, "#40395F");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, w, vy + 6);

  [{ tone: "#20203A", rise: 0.15, seed: 0.013 }, { tone: "#14151F", rise: 0.095, seed: 0.027 }].forEach(({ tone, rise, seed }) => {
    ctx.fillStyle = tone;
    ctx.beginPath();
    ctx.moveTo(0, vy + 4);
    for (let x = 0; x <= w + 5; x += 5) {
      const canopy = Math.sin(x * seed) * 0.42 + Math.sin(x * seed * 2.7 + 1.3) * 0.28 + Math.sin(x * seed * 6.1 + 0.4) * 0.14;
      ctx.lineTo(x, vy - h * rise * (0.62 + canopy * 0.42));
    }
    ctx.lineTo(w, vy + 4);
    ctx.closePath();
    ctx.fill();
  });

  const ground = ctx.createLinearGradient(0, vy, 0, h);
  ground.addColorStop(0, "#14151E");
  ground.addColorStop(1, "#0D0F15");
  ctx.fillStyle = ground;
  ctx.fillRect(0, vy, w, h - vy);

  const asphalt = ctx.createLinearGradient(0, vy, 0, h);
  asphalt.addColorStop(0, "#34354A");
  asphalt.addColorStop(0.3, "#25262F");
  asphalt.addColorStop(1, "#191A21");
  ctx.fillStyle = asphalt;
  quad(ctx, frame, -ROAD_HALF, ROAD_HALF, 1.4, 260);

  ctx.fillStyle = "rgba(226,228,238,0.62)";
  [-ROAD_HALF + 0.22, ROAD_HALF - 0.22].forEach((x) => quad(ctx, frame, x - 0.07, x + 0.07, 1.4, 260));
  ctx.fillStyle = "rgba(226,228,238,0.55)";
  [-3.75, 3.75].forEach((x) => {
    for (let z = 2.2; z < 130; z += 3.4) quad(ctx, frame, x - 0.06, x + 0.06, z, z + 1.5);
  });

  ctx.fillStyle = "#0F1016";
  quad(ctx, frame, -0.42, 0.42, 1.4, 260);
  ctx.fillStyle = "#8F92A2";
  [-0.3, 0.3].forEach((x) => quad(ctx, frame, x - 0.035, x + 0.035, 1.4, 260));

  [66, 44, 30, 21, 14.5, 10, 7].forEach((z) => {
    [-ROAD_HALF - 1, ROAD_HALF + 1].forEach((x) => {
      const side = Math.sign(x);
      const base = project(frame, x, z);
      const top = project(frame, x, z, 8);
      const head = project(frame, x - side * 2.3, z, 8.2);
      ctx.strokeStyle = "#2C2E3A";
      ctx.lineWidth = Math.max(base.s * 0.11, 1);
      ctx.beginPath();
      ctx.moveTo(base.x, base.y);
      ctx.lineTo(top.x, top.y);
      ctx.lineTo(head.x, head.y);
      ctx.stroke();
      ctx.globalCompositeOperation = "lighter";
      const radius = Math.max(head.s * 1.5, 5);
      ctx.globalAlpha = 0.72;
      ctx.drawImage(warm, head.x - radius, head.y - radius, radius * 2, radius * 2);
      const pool = project(frame, x - side * 2.8, z);
      ctx.globalAlpha = 0.09;
      ctx.save();
      ctx.translate(pool.x, pool.y);
      ctx.scale(1, 0.26);
      const spread = pool.s * 5.2;
      ctx.drawImage(warm, -spread, -spread, spread * 2, spread * 2);
      ctx.restore();
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    });
  });

  const vignette = ctx.createRadialGradient(frame.vx, h * 0.5, h * 0.3, frame.vx, h * 0.5, Math.max(w, h) * 0.85);
  vignette.addColorStop(0, "rgba(9,10,15,0)");
  vignette.addColorStop(1, "rgba(9,10,15,0.62)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);
  return layer;
}

function rounded(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function drawVehicle(ctx: CanvasRenderingContext2D, frame: Frame, vehicle: Vehicle, warm: HTMLCanvasElement, red: HTMLCanvasElement): Drawn {
  const lane = LANES[vehicle.lane];
  const kind = KINDS[vehicle.kind];
  const point = project(frame, lane.x, vehicle.z);
  const alpha = clamp((Z_FAR - vehicle.z) / 9) * clamp((vehicle.z - Z_NEAR + 0.2) * 3);
  const bw = kind.w * point.s;
  const bh = kind.h * point.s;
  const x = point.x;
  const y = point.y;
  const left = x - bw / 2;
  const top = y - bh;
  const rear = lane.dir > 0;
  ctx.globalAlpha = alpha;

  ctx.fillStyle = "rgba(4,5,8,0.62)";
  ctx.beginPath();
  ctx.ellipse(x, y, bw * 0.6, Math.max(bh * 0.09, 1), 0, 0, TAU);
  ctx.fill();

  ctx.fillStyle = "#08090D";
  rounded(ctx, left + bw * 0.05, y - bh * 0.14, bw * 0.19, bh * 0.14, bw * 0.03);
  ctx.fill();
  rounded(ctx, x + bw * 0.26, y - bh * 0.14, bw * 0.19, bh * 0.14, bw * 0.03);
  ctx.fill();

  const shade = ctx.createLinearGradient(0, top, 0, y);
  shade.addColorStop(0, vehicle.paint);
  shade.addColorStop(1, "#14151C");
  ctx.fillStyle = shade;
  if (kind.box) {
    rounded(ctx, left, top, bw, bh * 0.93, bw * 0.05);
    ctx.fill();
    ctx.fillStyle = rear ? "rgba(10,11,16,0.2)" : "#151824";
    if (rear) {
      ctx.fillRect(x - 0.5, top + bh * 0.05, Math.max(bw * 0.012, 1), bh * 0.72);
    } else {
      rounded(ctx, left + bw * 0.08, top + bh * 0.1, bw * 0.84, bh * 0.34, bw * 0.03);
      ctx.fill();
    }
  } else {
    ctx.beginPath();
    ctx.moveTo(left + bw * 0.06, y - bh * 0.5);
    ctx.quadraticCurveTo(left + bw * 0.13, top + bh * 0.03, left + bw * 0.28, top);
    ctx.lineTo(x + bw * 0.22, top);
    ctx.quadraticCurveTo(x + bw * 0.37, top + bh * 0.03, x + bw * 0.44, y - bh * 0.5);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#121521";
    ctx.beginPath();
    ctx.moveTo(left + bw * 0.14, y - bh * 0.54);
    ctx.lineTo(left + bw * 0.29, top + bh * 0.08);
    ctx.lineTo(x + bw * 0.21, top + bh * 0.08);
    ctx.lineTo(x + bw * 0.36, y - bh * 0.54);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(190,196,230,0.1)";
    ctx.beginPath();
    ctx.moveTo(left + bw * 0.3, top + bh * 0.09);
    ctx.lineTo(x - bw * 0.02, top + bh * 0.09);
    ctx.lineTo(x - bw * 0.2, y - bh * 0.54);
    ctx.lineTo(left + bw * 0.16, y - bh * 0.54);
    ctx.closePath();
    ctx.fill();
    const lower = ctx.createLinearGradient(0, y - bh * 0.56, 0, y);
    lower.addColorStop(0, vehicle.paint);
    lower.addColorStop(1, "#191A22");
    ctx.fillStyle = lower;
    rounded(ctx, left, y - bh * 0.54, bw, bh * 0.46, bw * 0.08);
    ctx.fill();
  }

  const lightY = y - bh * (kind.box ? 0.26 : 0.4);
  const lightW = bw * 0.2;
  const lightH = Math.max(bh * 0.075, 1);
  ctx.fillStyle = rear ? "#D93A45" : "#F4F1DF";
  [left + bw * 0.04, x + bw * 0.26].forEach((lx) => {
    rounded(ctx, lx, lightY, lightW, lightH, lightH / 2);
    ctx.fill();
  });
  ctx.globalCompositeOperation = "lighter";
  const sprite = rear ? red : warm;
  const radius = bw * (rear ? 0.17 : 0.34);
  [left + bw * 0.14, x + bw * 0.36].forEach((lx) => ctx.drawImage(sprite, lx - radius, lightY + lightH / 2 - radius, radius * 2, radius * 2));
  ctx.globalCompositeOperation = "source-over";

  const plateW = bw * 0.26;
  const plateH = Math.max(plateW * 0.24, 1.5);
  const plateX = x - plateW / 2;
  const plateY = y - bh * (kind.box ? 0.15 : 0.22);
  ctx.fillStyle = rear ? "#E5C94D" : "#ECEDF1";
  ctx.fillRect(plateX, plateY, plateW, plateH);
  if (plateW > 16) {
    ctx.fillStyle = "#15161C";
    const glyphs = 7;
    const glyphW = plateW * 0.085;
    for (let index = 0; index < glyphs; index += 1) {
      ctx.fillRect(plateX + plateW * 0.08 + index * plateW * 0.123, plateY + plateH * 0.22, glyphW, plateH * 0.56);
    }
  }
  ctx.globalAlpha = 1;
  return { vehicle, x, y, bw, bh, plate: [plateX, plateY, plateW, plateH], alpha };
}

function brackets(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, size: number) {
  ctx.beginPath();
  [[x, y, 1, 1], [x + w, y, -1, 1], [x + w, y + h, -1, -1], [x, y + h, 1, -1]].forEach(([cx, cy, dx, dy]) => {
    ctx.moveTo(cx + dx * size, cy);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx, cy + dy * size);
  });
  ctx.stroke();
}

function drawTracking(ctx: CanvasRenderingContext2D, frame: Frame, item: Drawn, isTarget: boolean, reveal: number, embedded: boolean) {
  const pad = Math.max(item.bw * 0.05, 2);
  const x = item.x - item.bw / 2 - pad;
  const y = item.y - item.bh - pad;
  const w = item.bw + pad * 2;
  const h = item.bh + pad * 2;
  if (x + w < 0 || x > frame.w || y > frame.h) return;
  // Keep the headline area free of tracking labels.
  if (!embedded && (frame.w >= 1024 ? x < frame.w * 0.44 : y + h > frame.h * 0.74)) return;
  const alpha = clamp((BOX_RANGE - item.vehicle.z) / 5) * clamp(item.alpha) * reveal;
  if (alpha <= 0) return;
  ctx.globalAlpha = alpha;
  const colour = isTarget ? VIOLET : "rgba(235,237,245,0.82)";
  ctx.strokeStyle = colour;
  ctx.lineWidth = isTarget ? 2 : 1.25;
  brackets(ctx, x, y, w, h, clamp(Math.min(w, h) * 0.2, 5, 26));
  if (w > 34) {
    const label = `T${String(item.vehicle.id).padStart(2, "0")} ${KINDS[item.vehicle.kind].name}`;
    ctx.font = "600 10px 'JetBrains Mono', ui-monospace, Menlo, monospace";
    const tag = ctx.measureText(label).width + 8;
    const tagY = Math.max(y - 15, 0);
    ctx.fillStyle = isTarget ? VIOLET : "rgba(235,237,245,0.9)";
    ctx.fillRect(x, tagY, tag, 14);
    ctx.fillStyle = "#14151E";
    ctx.fillText(label, x + 4, tagY + 10.5);
  }
  ctx.globalAlpha = 1;
}

function drawTarget(ctx: CanvasRenderingContext2D, item: Drawn, anchor: { x: number; y: number } | null, time: number, reveal: number) {
  const [px, py, pw, ph] = item.plate;
  const pad = Math.max(pw * 0.14, 3);
  ctx.globalAlpha = reveal;
  ctx.strokeStyle = VIOLET;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(px - pad, py - pad, pw + pad * 2, ph + pad * 2);
  if (anchor) {
    const sx = px + pw + pad;
    const sy = py + ph / 2;
    const elbow = sx + (anchor.x - sx) * 0.42;
    ctx.strokeStyle = "rgba(183,174,245,0.72)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(elbow, sy);
    ctx.lineTo(elbow, anchor.y);
    ctx.lineTo(anchor.x, anchor.y);
    ctx.stroke();
    const first = Math.abs(elbow - sx);
    const second = Math.abs(anchor.y - sy);
    const third = Math.abs(anchor.x - elbow);
    let travelled = ((time * 0.55) % 1) * (first + second + third);
    let dotX = sx;
    let dotY = sy;
    if (travelled < first) dotX = sx + Math.sign(elbow - sx) * travelled;
    else if ((travelled -= first) < second) { dotX = elbow; dotY = sy + Math.sign(anchor.y - sy) * travelled; } else {
      travelled -= second;
      dotX = elbow + Math.sign(anchor.x - elbow) * travelled;
      dotY = anchor.y;
    }
    ctx.fillStyle = "#FFFFFF";
    ctx.beginPath();
    ctx.arc(dotX, dotY, 2.4, 0, TAU);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawHud(ctx: CanvasRenderingContext2D, frame: Frame, time: number, animated: boolean, embedded: boolean) {
  const { w, h } = frame;
  const inset = embedded ? 4 : w < 640 ? 12 : 22;
  const top = embedded ? 18 : w < 640 ? 66 : 84;
  ctx.strokeStyle = "rgba(235,237,245,0.34)";
  ctx.lineWidth = 1;
  if (!embedded && w >= 1024) brackets(ctx, w * 0.36, top - 14, w * 0.64 - inset, h - top - 112, 24);
  const seconds = Math.floor(time);
  const stamp = `00:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}:${String(Math.floor((time % 1) * 25)).padStart(2, "0")}`;
  ctx.font = "600 11px 'JetBrains Mono', ui-monospace, Menlo, monospace";
  ctx.textAlign = "right";
  ctx.fillStyle = "rgba(236,237,243,0.9)";
  ctx.fillText(`CAM 04  ${stamp}`, w - inset - 12, top + 4);
  const width = ctx.measureText(`CAM 04  ${stamp}`).width;
  ctx.textAlign = "left";
  if (!animated || Math.floor(time * 1.4) % 2 === 0) {
    ctx.fillStyle = "#E5484D";
    ctx.beginPath();
    ctx.arc(w - inset - 24 - width, top, 3.5, 0, TAU);
    ctx.fill();
  }
}

export function OpeningScene({ anchorRef, animated, embedded = false }: { anchorRef?: RefObject<HTMLElement>; animated: boolean; embedded?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const parent = canvas.parentElement!;
    const vehicles = createVehicles();
    const warm = glowSprite("rgba(255,226,170,1)");
    const red = glowSprite("rgba(255,70,76,1)");
    let frame: Frame = { w: 1, h: 1, vx: 0, vy: 0, f: 1 };
    let background: HTMLCanvasElement | null = null;
    let dpr = 1;
    let raf = 0;
    let last = performance.now();
    let elapsed = animated ? 0 : 8;
    let targetId: number | null = null;
    let anchor: { x: number; y: number } | null = null;
    let anchorCheck = 0;

    const readAnchor = () => {
      const element = anchorRef?.current;
      if (!element || frame.w < 1024) {
        anchor = null;
        return;
      }
      const box = element.getBoundingClientRect();
      const origin = canvas.getBoundingClientRect();
      anchor = { x: box.left - origin.left, y: box.top - origin.top + 34 };
    };

    const resize = () => {
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      if (!w || !h) return;
      dpr = Math.min(window.devicePixelRatio || 1, embedded ? 1.25 : 2);
      canvas.width = Math.ceil(w * dpr);
      canvas.height = Math.ceil(h * dpr);
      const wide = !embedded && w >= 1024;
      const vx = w * (wide ? 0.61 : 0.5);
      const vy = h * (wide ? 0.37 : 0.33);
      frame = { w, h, vx, vy, f: ((h - vy) * NEAR_EDGE_Z) / CAMERA_HEIGHT };
      background = paintBackground(frame, dpr, warm);
      readAnchor();
      if (!animated) draw();
    };

    const draw = () => {
      if (!background) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.drawImage(background, 0, 0, frame.w, frame.h);
      const ordered = [...vehicles].sort((a, b) => b.z - a.z);
      const drawn = ordered.map((vehicle) => drawVehicle(ctx, frame, vehicle, warm, red));
      const reveal = clamp((elapsed - 0.9) / 0.8);
      const current = drawn.find((item) => item.vehicle.id === targetId);
      if (!current || current.vehicle.z > 21 || current.vehicle.z < 5) {
        const next = drawn
          .filter((item) => item.vehicle.lane === TARGET_LANE && item.vehicle.z >= 5.4 && item.vehicle.z < 17)
          .sort((a, b) => a.vehicle.z - b.vehicle.z)[0];
        targetId = next?.vehicle.id ?? null;
      }
      drawn.filter((item) => item.vehicle.z < BOX_RANGE).forEach((item) => drawTracking(ctx, frame, item, item.vehicle.id === targetId, reveal, embedded));
      const target = drawn.find((item) => item.vehicle.id === targetId);
      if (target) drawTarget(ctx, target, anchor, elapsed, reveal);

      if (animated) {
        const sweep = ((elapsed * 0.13) % 1) * (frame.h + 120) - 60;
        const band = ctx.createLinearGradient(0, sweep - 54, 0, sweep);
        band.addColorStop(0, "rgba(183,174,245,0)");
        band.addColorStop(1, "rgba(183,174,245,0.075)");
        ctx.fillStyle = band;
        ctx.fillRect(0, sweep - 54, frame.w, 54);
        ctx.fillStyle = "rgba(201,196,240,0.3)";
        ctx.fillRect(0, sweep, frame.w, 1);
      }
      drawHud(ctx, frame, elapsed, animated, embedded);
    };

    let visible = true;
    const tick = (now: number) => {
      if (!visible) {
        raf = 0;
        return;
      }
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      elapsed += delta;
      vehicles.forEach((vehicle) => {
        const lane = LANES[vehicle.lane];
        vehicle.z += lane.dir * lane.speed * delta;
        if (vehicle.z > Z_FAR) vehicle.z = Z_NEAR;
        if (vehicle.z < Z_NEAR) vehicle.z = Z_FAR;
      });
      anchorCheck += delta;
      if (anchorCheck > 0.4) {
        anchorCheck = 0;
        readAnchor();
      }
      draw();
      raf = requestAnimationFrame(tick);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(parent);
    // Only draw while the scene is on screen, so several scenes can share a long page.
    const viewport = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible && animated && !raf) {
        last = performance.now();
        raf = requestAnimationFrame(tick);
      }
    });
    viewport.observe(parent);
    resize();
    if (animated) raf = requestAnimationFrame(tick);
    else draw();
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      viewport.disconnect();
    };
  }, [anchorRef, animated, embedded]);

  return <canvas ref={canvasRef} aria-hidden="true" className="absolute inset-0 h-full w-full" />;
}
