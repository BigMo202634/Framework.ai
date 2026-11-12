"use client";

// Plays the edit without rendering it: one <video> of the proxy jumps from clip to clip, and the
// frame is cropped with CSS to the output format, zoomed for punch-ins. Close to the final render,
// not frame-exact (the render is).

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Aspect, Plan } from "@/lib/api";
import { outToSrc, planDur, starts } from "@/lib/timeline";

export type PreviewHandle = { seek: (t: number) => void; toggle: () => void; playing: () => boolean };

const RATIO: Record<Aspect, number | null> = { "9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1, "4:5": 4 / 5, source: null };

type Props = {
  src: string;
  plan: Plan;
  sourceRatio: number;
  onTime: (t: number) => void;
  onPlayingChange: (playing: boolean) => void;
};

const Preview = forwardRef<PreviewHandle, Props>(function Preview({ src, plan, sourceRatio, onTime, onPlayingChange }, ref) {
  const video = useRef<HTMLVideoElement | null>(null);
  const seg = useRef(0);
  const planRef = useRef(plan);
  const raf = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [segIndex, setSegIndex] = useState(0);
  const [ready, setReady] = useState(false);
  planRef.current = plan;

  const setSeg = (i: number) => {
    seg.current = i;
    setSegIndex(i);
  };

  const seek = useCallback((t: number) => {
    const p = planRef.current;
    const v = video.current;
    if (!v || !p.segments.length) return;
    const { i, src: s } = outToSrc(p, Math.max(0, Math.min(t, planDur(p))));
    setSeg(i);
    v.currentTime = s;
    onTime(t);
  }, [onTime]);

  const tick = useCallback(() => {
    const v = video.current;
    const p = planRef.current;
    if (!v || !p.segments.length) return;
    let i = Math.min(seg.current, p.segments.length - 1);
    const s = p.segments[i];
    if (v.currentTime >= s.src_out - 0.015 || v.currentTime < s.src_in - 0.25) {
      if (v.currentTime >= s.src_out - 0.015) i += 1;
      if (i >= p.segments.length) {
        v.pause();
        onTime(planDur(p));
        return;
      }
      setSeg(i);
      v.currentTime = p.segments[i].src_in;
    }
    const cur = p.segments[i];
    onTime(starts(p)[i] + Math.max(0, Math.min(v.currentTime - cur.src_in, cur.src_out - cur.src_in)));
    raf.current = requestAnimationFrame(tick);
  }, [onTime]);

  useEffect(() => () => { if (raf.current) cancelAnimationFrame(raf.current); }, []);

  useImperativeHandle(ref, () => ({
    seek,
    playing: () => playing,
    toggle: () => {
      const v = video.current;
      if (!v) return;
      if (v.paused) {
        const p = planRef.current;
        const st = starts(p);
        const last = p.segments.length - 1;
        // At the end: start over.
        if (seg.current >= last && v.currentTime >= p.segments[last].src_out - 0.05) seek(0);
        else if (v.currentTime < p.segments[seg.current].src_in || v.currentTime > p.segments[seg.current].src_out) seek(st[seg.current]);
        void v.play();
      } else v.pause();
    },
  }), [seek, playing]);

  const target = RATIO[plan.output.aspect] ?? sourceRatio;
  const clip = plan.segments[Math.min(segIndex, plan.segments.length - 1)];
  const zoom = clip?.zoom ?? 1;
  const fx = (clip?.focus_x ?? 0.5) * 100;
  const fy = (clip?.focus_y ?? 0.4) * 100;

  return (
    <div className="flex h-full w-full items-center justify-center bg-black/60 p-3">
      <div className="relative max-h-full max-w-full overflow-hidden rounded bg-black shadow-2xl"
        style={{ aspectRatio: String(target), height: target < 1 ? "100%" : undefined, width: target >= 1 ? "100%" : undefined }}>
        <video
          ref={video}
          src={src}
          preload="auto"
          playsInline
          className="absolute inset-0 h-full w-full object-cover"
          style={{ objectPosition: `${fx}% ${fy}%`, transform: `scale(${zoom})`, transformOrigin: `${fx}% ${fy}%` }}
          onLoadedData={() => { setReady(true); seek(0); }}
          onPlay={() => { setPlaying(true); onPlayingChange(true); raf.current = requestAnimationFrame(tick); }}
          onPause={() => { setPlaying(false); onPlayingChange(false); if (raf.current) cancelAnimationFrame(raf.current); }}
        />
        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-xs text-neutral-400">
            Preparing a light preview copy of your video…
          </div>
        )}
        {zoom > 1 && <span className="absolute right-2 top-2 rounded bg-sky-500/90 px-1.5 py-0.5 text-[10px] font-semibold text-black">PUNCH-IN {zoom.toFixed(2)}×</span>}
      </div>
    </div>
  );
});

export default Preview;
