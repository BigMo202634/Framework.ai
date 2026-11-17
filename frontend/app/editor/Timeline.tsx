"use client";

// Horizontal multi-track timeline, DaVinci-style: ruler, V1 (clips), A1 (waveform), T (spoken
// words). Drag a clip's edge to trim it (later clips ripple), click to select, click the ruler or
// drag the playhead to move it. Ctrl/Cmd + scroll zooms, scroll moves sideways.

import { memo, useEffect, useMemo, useRef } from "react";
import type { Plan, Waveform, Word } from "@/lib/api";
import { planDur, segDur, short, srcToOut, starts } from "@/lib/timeline";

const LABEL_W = 56;

type Props = {
  plan: Plan;
  pps: number; // pixels per second
  playhead: number;
  selected: number | null;
  waveform: Waveform | null;
  words: Word[];
  onSeek: (t: number) => void;
  onSelect: (i: number | null) => void;
  onTrimStart: () => void;
  onTrim: (i: number, edge: "in" | "out", src: number) => void;
  onZoom: (pps: number) => void;
};

function tickStep(pps: number): number {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  return steps.find((s) => s * pps >= 70) ?? 300;
}

export default function Timeline(props: Props) {
  const { plan, pps, playhead, onSeek, onZoom } = props;
  const scroller = useRef<HTMLDivElement | null>(null);
  const total = planDur(plan);
  const width = Math.max(total * pps + 200, 400);
  const following = useRef(true);

  // Keep the playhead in view while playing.
  useEffect(() => {
    const el = scroller.current;
    if (!el || !following.current) return;
    const x = playhead * pps;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - LABEL_W - 40) el.scrollLeft = Math.max(0, x - 80);
  }, [playhead, pps]);

  function timeAt(clientX: number) {
    const el = scroller.current!;
    const rect = el.getBoundingClientRect();
    return Math.max(0, Math.min(total, (clientX - rect.left - LABEL_W + el.scrollLeft) / pps));
  }

  function scrub(e: React.PointerEvent) {
    e.preventDefault();
    onSeek(timeAt(e.clientX));
    const move = (ev: PointerEvent) => onSeek(timeAt(ev.clientX));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function wheel(e: React.WheelEvent) {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      onZoom(Math.max(4, Math.min(400, pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
    }
  }

  const step = tickStep(pps);
  const ticks = useMemo(() => {
    const out: number[] = [];
    for (let t = 0; t <= total + step; t += step) out.push(t);
    return out;
  }, [total, step]);

  return (
    <div className="relative flex h-full w-full min-w-0 flex-col select-none bg-[#14161c] text-xs">
      <div ref={scroller} className="relative flex-1 overflow-x-auto overflow-y-hidden" onWheel={wheel}
        onScroll={() => { following.current = false; }}
        onPointerDown={() => { following.current = true; }}>
        <div className="relative h-full" style={{ width: width + LABEL_W }}>
          {/* Ruler */}
          <div className="sticky top-0 z-20 flex h-7 border-b border-white/10 bg-[#1b1e26]">
            <div className="sticky left-0 z-30 h-full shrink-0 border-r border-white/10 bg-[#1b1e26]" style={{ width: LABEL_W }} />
            <div className="relative h-full flex-1 cursor-pointer" onPointerDown={scrub}>
              {ticks.map((t) => (
                <div key={t} className="absolute top-0 h-full border-l border-white/15 pl-1 pt-1 text-[10px] text-neutral-400"
                  style={{ left: t * pps }}>{short(t)}</div>
              ))}
            </div>
          </div>

          <Tracks plan={plan} pps={pps} selected={props.selected} waveform={props.waveform} words={props.words}
            onSelect={props.onSelect} onTrimStart={props.onTrimStart} onTrim={props.onTrim} />

          {/* Playhead */}
          <div className="pointer-events-none absolute bottom-0 top-0 z-30" style={{ left: LABEL_W + playhead * pps }}>
            <div className="pointer-events-auto absolute -left-[7px] top-0 h-3 w-[15px] cursor-ew-resize rounded-b-sm bg-red-500"
              onPointerDown={scrub} />
            <div className="absolute left-0 top-0 h-full w-px bg-red-500" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Tracks don't depend on the playhead, so they don't redraw 60 times a second during playback.
type TrackProps = Omit<Props, "playhead" | "onSeek" | "onZoom">;

const Tracks = memo(function Tracks({ plan, pps, selected, waveform, words, onSelect, onTrimStart, onTrim }: TrackProps) {
  const st = starts(plan);

  function dragEdge(e: React.PointerEvent, i: number, edge: "in" | "out") {
    e.stopPropagation();
    e.preventDefault();
    onSelect(i);
    onTrimStart();
    const x0 = e.clientX;
    const s = plan.segments[i];
    const v0 = edge === "in" ? s.src_in : s.src_out;
    // Dragging the left edge right shortens the clip: moving src_in later.
    const move = (ev: PointerEvent) => onTrim(i, edge, v0 + (ev.clientX - x0) / pps);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const placedWords = useMemo(() => {
    if (pps < 25) return [];
    const placed = words.flatMap((w) => {
      const t = srcToOut(plan, w.start) ?? srcToOut(plan, (w.start + w.end) / 2);
      return t === null ? [] : [{ w, x: t * pps, max: 0 }];
    }).sort((a, b) => a.x - b.x);
    // Each word gets the room up to the next one; words with no room are left out until you zoom in.
    placed.forEach((p, k) => { p.max = (placed[k + 1]?.x ?? p.x + 200) - p.x - 3; });
    return placed.filter((p) => p.max >= 14);
  }, [words, plan, pps]);

  return (
    <div className="relative">
      <Track label="V1">
        {plan.segments.map((s, i) => (
          <div key={i}
            className={`group absolute top-1 bottom-1 overflow-hidden rounded-[3px] border ${
              selected === i ? "border-amber-300 ring-1 ring-amber-300" : "border-black/40"
            } ${s.zoom > 1 ? "bg-sky-700/90" : "bg-indigo-800/90"}`}
            style={{ left: st[i] * pps, width: Math.max(2, segDur(s) * pps - 1) }}
            onPointerDown={(e) => { e.stopPropagation(); onSelect(i); }}
            title={`Clip ${i + 1}: source ${short(s.src_in)} to ${short(s.src_out)}${s.zoom > 1 ? `, punch-in ${s.zoom}×` : ""}`}>
            {segDur(s) * pps > 40 && (
              <span className="pointer-events-none absolute left-1.5 top-1 truncate text-[10px] font-medium text-white/90">
                {s.zoom > 1 ? `🔍 ${s.zoom.toFixed(2)}×` : `Clip ${i + 1}`}
              </span>
            )}
            <div className="absolute inset-y-0 left-0 w-2 cursor-ew-resize bg-white/0 hover:bg-amber-300/70"
              onPointerDown={(e) => dragEdge(e, i, "in")} />
            <div className="absolute inset-y-0 right-0 w-2 cursor-ew-resize bg-white/0 hover:bg-amber-300/70"
              onPointerDown={(e) => dragEdge(e, i, "out")} />
          </div>
        ))}
      </Track>

      <Track label="A1" tall>
        {plan.segments.map((s, i) => (
          <div key={i} className={`absolute top-1 bottom-1 overflow-hidden rounded-[3px] border ${
            selected === i ? "border-amber-300" : "border-black/40"} bg-emerald-900/70`}
            style={{ left: st[i] * pps, width: Math.max(2, segDur(s) * pps - 1) }}
            onPointerDown={(e) => { e.stopPropagation(); onSelect(i); }}>
            {waveform && <Wave wave={waveform} from={s.src_in} to={s.src_out} pps={pps} />}
          </div>
        ))}
      </Track>

      <Track label="TEXT">
        {placedWords.map(({ w, x, max }) => (
          <span key={w.i} className="absolute top-2 overflow-hidden whitespace-nowrap rounded-sm bg-white/5 px-0.5 text-[10px] text-neutral-300"
            style={{ left: x, maxWidth: max }}
            title={`${w.text} (${short(w.start)} in the original)`}>
            {w.text}
          </span>
        ))}
        {pps < 25 && words.length > 0 && (
          <span className="absolute left-2 top-2 text-[10px] text-neutral-500">Zoom in to see the words</span>
        )}
      </Track>
    </div>
  );
});

function Track({ label, tall, children }: { label: string; tall?: boolean; children: React.ReactNode }) {
  return (
    <div className={`relative flex border-b border-white/5 ${tall ? "h-16" : "h-12"}`}>
      <div className="sticky left-0 z-10 flex shrink-0 items-center justify-center border-r border-white/10 bg-[#1b1e26] font-semibold text-neutral-400"
        style={{ width: LABEL_W }}>{label}</div>
      <div className="relative flex-1">{children}</div>
    </div>
  );
}

const Wave = memo(function Wave({ wave, from, to, pps }: { wave: Waveform; from: number; to: number; pps: number }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const w = Math.min(16000, Math.max(2, Math.round((to - from) * pps)));
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const h = c.height;
    ctx.clearRect(0, 0, c.width, h);
    ctx.fillStyle = "rgba(110, 231, 183, 0.85)";
    const a = Math.floor(from * wave.rate);
    const b = Math.ceil(to * wave.rate);
    const n = Math.max(1, b - a);
    for (let x = 0; x < c.width; x++) {
      const k0 = a + Math.floor((x / c.width) * n);
      const k1 = Math.max(k0 + 1, a + Math.floor(((x + 1) / c.width) * n));
      let peak = 0;
      for (let k = k0; k < k1 && k < wave.peaks.length; k++) peak = Math.max(peak, wave.peaks[k]);
      const bar = Math.max(1, (peak / 100) * (h - 2));
      ctx.fillRect(x, (h - bar) / 2, 1, bar);
    }
  }, [wave, from, to, w]);
  return <canvas ref={canvas} width={w} height={52} className="h-full" style={{ width: w }} />;
});
