// Pure timeline maths and edits. Every manual edit in the editor goes through here and returns a
// new plan, so undo/redo is just a stack of plans. Times: "src" = original video, "out" = edited.

import type { Plan, RemovedPart, Segment } from "./api";

export const MIN_CLIP = 0.2; // matches the backend validator
export const MAX_ZOOM = 2.0;

export const segDur = (s: Segment) => s.src_out - s.src_in;
export const planDur = (p: Plan) => p.segments.reduce((t, s) => t + segDur(s), 0);

/** Start of each segment on the edited timeline. */
export function starts(p: Plan): number[] {
  const out: number[] = [];
  let t = 0;
  for (const s of p.segments) {
    out.push(t);
    t += segDur(s);
  }
  return out;
}

/** Which segment plays at edited time t (clamped to the ends). */
export function segAt(p: Plan, t: number): number {
  const st = starts(p);
  for (let i = st.length - 1; i >= 0; i--) if (t >= st[i] - 1e-6) return i;
  return 0;
}

export function outToSrc(p: Plan, t: number): { i: number; src: number } {
  const i = segAt(p, t);
  const s = p.segments[i];
  const off = Math.min(Math.max(0, t - starts(p)[i]), segDur(s));
  return { i, src: s.src_in + off };
}

/** Edited time of a source moment, or null if that moment was cut. */
export function srcToOut(p: Plan, src: number): number | null {
  const st = starts(p);
  for (let i = 0; i < p.segments.length; i++) {
    const s = p.segments[i];
    if (src >= s.src_in && src <= s.src_out) return st[i] + (src - s.src_in);
  }
  return null;
}

const withSegments = (p: Plan, segments: Segment[]): Plan => ({ ...p, segments });

/** Move one edge of a clip. Later clips ripple along automatically. */
export function trim(p: Plan, i: number, edge: "in" | "out", value: number, sourceDur: number): Plan {
  const segs = p.segments.map((s) => ({ ...s }));
  const s = segs[i];
  if (edge === "in") s.src_in = clamp(value, 0, s.src_out - MIN_CLIP);
  else s.src_out = clamp(value, s.src_in + MIN_CLIP, sourceDur);
  return withSegments(p, segs);
}

/** Cut the clip under edited time t into two. Returns null if either half would be too short. */
export function split(p: Plan, t: number): { plan: Plan; index: number } | null {
  const { i, src } = outToSrc(p, t);
  const s = p.segments[i];
  if (src - s.src_in < MIN_CLIP || s.src_out - src < MIN_CLIP) return null;
  const a = { ...s, src_out: src };
  const b = { ...s, src_in: src };
  const segs = [...p.segments.slice(0, i), a, b, ...p.segments.slice(i + 1)];
  return { plan: withSegments(p, segs), index: i + 1 };
}

/** Remove a clip; the rest closes the gap (ripple delete). */
export function remove(p: Plan, i: number): Plan | null {
  if (p.segments.length <= 1) return null;
  return withSegments(p, p.segments.filter((_, k) => k !== i));
}

export function setClip(p: Plan, i: number, patch: Partial<Segment>): Plan {
  return withSegments(p, p.segments.map((s, k) => (k === i ? { ...s, ...patch } : s)));
}

export function togglePunch(p: Plan, i: number, zoom = 1.15): Plan {
  const s = p.segments[i];
  return setClip(p, i, { zoom: s.zoom > 1 ? 1 : zoom });
}

/** Put a part the director cut back into the edit, joining it to its neighbours. */
export function restore(p: Plan, part: RemovedPart, sourceDur: number): Plan {
  const add: Segment = {
    src_in: Math.max(0, part.start - 0.06),
    src_out: Math.min(sourceDur, part.end + 0.06),
    zoom: 1,
    reason: `restored ${part.kind}`,
  };
  const segs = [...p.segments.map((s) => ({ ...s })), add].sort((a, b) => a.src_in - b.src_in);
  const merged: Segment[] = [];
  for (const s of segs) {
    const last = merged[merged.length - 1];
    if (last && s.src_in <= last.src_out + 0.08) last.src_out = Math.max(last.src_out, s.src_out);
    else merged.push(s);
  }
  return {
    ...p,
    segments: merged,
    removed: p.removed.filter((r) => !(r.start === part.start && r.end === part.end)),
  };
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function timecode(t: number, fps = 30): string {
  const sign = t < 0 ? "-" : "";
  t = Math.abs(t);
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const f = Math.floor((t % 1) * fps);
  return `${sign}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}:${String(f).padStart(2, "0")}`;
}

export const short = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
