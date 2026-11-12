"use client";

// The editing room: top bar, inspector (left), preview (centre), chat (right), timeline (bottom).
// The plan is the single source of truth. Every change, from the AI or by hand, replaces it and
// goes on the undo stack. Manual edits are saved in this browser so a refresh loses nothing.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  exportUrl, getJob, getTranscript, getWaveform, planEdit, proxyUrl, sendChat, startRender,
  type Aspect, type EditRequest, type Job, type MediaSummary, type Plan, type Waveform, type Word,
} from "@/lib/api";
import {
  MAX_ZOOM, planDur, remove, restore, segAt, segDur, setClip, short, split, timecode, togglePunch, trim,
} from "@/lib/timeline";
import Preview, { type PreviewHandle } from "./Preview";
import Timeline from "./Timeline";

const ASPECTS: { value: Aspect; label: string }[] = [
  { value: "9:16", label: "9:16 Reels / TikTok" },
  { value: "16:9", label: "16:9 YouTube" },
  { value: "1:1", label: "1:1 Square" },
  { value: "4:5", label: "4:5 Feed" },
  { value: "source", label: "Original" },
];

const KIND_LABEL: Record<string, string> = {
  filler: "Filler", stutter: "Stutter", retake: "False start", repetition: "Said twice", off_message: "Off message",
};

type Msg = { from: "you" | "editor"; text: string };

const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

export default function Editor({ media }: { media: MediaSummary }) {
  const [req, setReq] = useState<EditRequest>({ aspect: "9:16", remove_silences: true, punch_ins: true, creative_cuts: true });
  const [plan, setPlanState] = useState<Plan | null>(null);
  const [past, setPast] = useState<Plan[]>([]);
  const [future, setFuture] = useState<Plan[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [pps, setPps] = useState(20);
  const [wave, setWave] = useState<Waveform | null>(null);
  const [words, setWords] = useState<Word[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const [leftTab, setLeftTab] = useState<"clip" | "cuts">("cuts");
  const preview = useRef<PreviewHandle | null>(null);
  const planRef = useRef<Plan | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEnd = useRef<HTMLDivElement | null>(null);
  planRef.current = plan;
  const key = `fw-plan-${media.media_id}`;

  // ------------------------------------------------------------------ plan + history
  const commit = useCallback((next: Plan) => {
    const cur = planRef.current;
    if (cur) setPast((p) => [...p.slice(-99), cur]);
    setFuture([]);
    setPlanState(next);
  }, []);
  // For live drags: change the plan without a history entry (one entry is pushed at drag start).
  const live = useCallback((next: Plan) => setPlanState(next), []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (!p.length || !planRef.current) return p;
      setFuture((f) => [planRef.current!, ...f]);
      setPlanState(p[p.length - 1]);
      return p.slice(0, -1);
    });
  }, []);
  const redo = useCallback(() => {
    setFuture((f) => {
      if (!f.length || !planRef.current) return f;
      setPast((p) => [...p, planRef.current!]);
      setPlanState(f[0]);
      return f.slice(1);
    });
  }, []);

  useEffect(() => { if (plan) store.set(key, JSON.stringify(plan)); }, [plan, key]);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [messages]);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  // ------------------------------------------------------------------ loading
  const loadSide = useCallback(() => {
    getWaveform(media.media_id).then(setWave).catch(() => setWave(null));
    getTranscript(media.media_id).then((t) => setWords(t.words)).catch(() => setWords([]));
  }, [media.media_id]);

  const autoEdit = useCallback(async (r: EditRequest) => {
    setError(null);
    setBusy(r.creative_cuts ? "Listening to your video and making the first cut… (first time: a few minutes)" : "Making the first cut…");
    try {
      const res = await planEdit(media.media_id, r);
      commit(res.plan);
      setWarnings(res.validation.warnings);
      setSelected(null);
      setMessages((m) => [...m, { from: "editor", text: `${res.plan.summary}${res.plan.message ? ` Your message, as I heard it: ${res.plan.message}` : ""} Edit the timeline by hand, or tell me what to change.` }]);
      if (res.plan.removed.length) setLeftTab("cuts");
      loadSide();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }, [media.media_id, commit, loadSide]);

  useEffect(() => {
    const saved = store.get(key);
    if (saved) {
      try {
        const p = JSON.parse(saved) as Plan;
        setPlanState(p);
        setReq((q) => ({ ...q, aspect: p.output.aspect }));
        setMessages([{ from: "editor", text: "Welcome back. Your last edit is restored." }]);
        loadSide();
        return;
      } catch { /* fall through to a fresh edit */ }
    }
    void autoEdit({ aspect: "9:16", remove_silences: true, punch_ins: true, creative_cuts: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------------ editing actions
  const seek = useCallback((t: number) => { preview.current?.seek(t); setPlayhead(t); }, []);
  const onSelect = useCallback((i: number | null) => { setSelected(i); if (i !== null) setLeftTab("clip"); }, []);
  const onTrimStart = useCallback(() => { const cur = planRef.current; if (cur) { setPast((p) => [...p.slice(-99), cur]); setFuture([]); } }, []);
  const onTrim = useCallback((i: number, edge: "in" | "out", src: number) => {
    const cur = planRef.current;
    if (cur) live(trim(cur, i, edge, src, media.duration_s));
  }, [live, media.duration_s]);

  const doSplit = useCallback(() => {
    const cur = planRef.current;
    if (!cur) return;
    const r = split(cur, playhead);
    if (r) { commit(r.plan); setSelected(r.index); }
  }, [commit, playhead]);
  const doDelete = useCallback(() => {
    const cur = planRef.current;
    if (!cur || selected === null) return;
    const next = remove(cur, selected);
    if (next) { commit(next); setSelected(null); }
  }, [commit, selected]);
  const doPunch = useCallback(() => {
    const cur = planRef.current;
    if (!cur) return;
    const i = selected ?? segAt(cur, playhead);
    commit(togglePunch(cur, i));
    setSelected(i);
  }, [commit, selected, playhead]);

  // Keyboard shortcuts (like an NLE). Ignored while typing in a field.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      const typing = (el.tagName === "INPUT" && !["range", "checkbox"].includes((el as HTMLInputElement).type))
        || el.tagName === "TEXTAREA" || el.tagName === "SELECT";
      if (typing) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
      else if (e.key === " ") { e.preventDefault(); preview.current?.toggle(); }
      else if (e.key.toLowerCase() === "s" || (mod && e.key.toLowerCase() === "b")) { e.preventDefault(); doSplit(); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); doDelete(); }
      else if (e.key.toLowerCase() === "p") doPunch();
      else if (e.key === "ArrowLeft") seek(Math.max(0, playhead - (e.shiftKey ? 1 : 1 / 30)));
      else if (e.key === "ArrowRight") seek(playhead + (e.shiftKey ? 1 : 1 / 30));
      else if (e.key === "=" || e.key === "+") setPps((p) => Math.min(400, p * 1.25));
      else if (e.key === "-") setPps((p) => Math.max(4, p / 1.25));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, doSplit, doDelete, doPunch, seek, playhead]);

  // ------------------------------------------------------------------ chat + render
  async function chat() {
    const text = draft.trim();
    if (!text || !plan) return;
    setDraft("");
    setMessages((m) => [...m, { from: "you", text }]);
    if (/^\s*undo\b/i.test(text)) { undo(); setMessages((m) => [...m, { from: "editor", text: "Undone." }]); return; }
    setBusy("The editor is thinking…");
    try {
      const r = await sendChat(media.media_id, text, plan);
      setMode(r.mode);
      if (r.changes.length) commit(r.plan);
      setWarnings(r.validation.warnings);
      setMessages((m) => [...m, { from: "editor", text: r.reply }]);
    } catch (e) {
      setMessages((m) => [...m, { from: "editor", text: `Something went wrong: ${e instanceof Error ? e.message : e}` }]);
    } finally {
      setBusy(null);
    }
  }

  async function render() {
    if (!plan) return;
    setError(null);
    try {
      const j = await startRender(media.media_id, req, plan);
      setJob(j);
      timer.current = setInterval(async () => {
        try {
          const next = await getJob(j.job_id);
          setJob(next);
          if (next.status === "done" || next.status === "failed") {
            if (timer.current) clearInterval(timer.current);
            if (next.status === "failed") setError(next.error ?? "Render failed");
          }
        } catch (e) {
          if (timer.current) clearInterval(timer.current);
          fail(e);
        }
      }, 800);
    } catch (e) {
      fail(e);
    }
  }

  const rendering = job && (job.status === "queued" || job.status === "running");
  const total = plan ? planDur(plan) : 0;
  const sel = plan && selected !== null ? plan.segments[selected] : null;

  // ------------------------------------------------------------------ layout
  return (
    <div className="grid h-screen w-screen grid-cols-[minmax(0,1fr)] grid-rows-[48px_minmax(0,1fr)_minmax(220px,36vh)] overflow-hidden bg-[#0d0f14] text-neutral-200">
      {/* Top bar */}
      <header className="flex min-w-0 items-center gap-3 border-b border-white/10 bg-[#111319] px-3 text-sm">
        <Link href="/" className="font-semibold tracking-tight text-white">FRAMEWORK <span className="text-violet-400">AI</span></Link>
        <span className="truncate text-neutral-500">/ {media.original_name}</span>
        <div className="ml-auto flex items-center gap-2">
          <select className="rounded border border-white/10 bg-[#1b1e26] px-2 py-1" value={plan?.output.aspect ?? req.aspect}
            onChange={(e) => {
              const aspect = e.target.value as Aspect;
              setReq({ ...req, aspect });
              if (plan) commit({ ...plan, output: { ...plan.output, aspect } });
            }}>
            {ASPECTS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
          <details className="relative">
            <summary className="cursor-pointer list-none rounded border border-white/10 px-3 py-1 hover:bg-white/5">Auto edit ▾</summary>
            <div className="absolute right-0 z-50 mt-1 w-64 space-y-2 rounded-lg border border-white/10 bg-[#1b1e26] p-3 shadow-xl">
              {([
                ["remove_silences", "Remove silences"],
                ["punch_ins", "Punch-ins on cuts"],
                ["creative_cuts", "Cut fillers & repeats"],
              ] as const).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2">
                  <input type="checkbox" checked={req[k]} onChange={(e) => setReq({ ...req, [k]: e.target.checked })} />
                  {label}
                </label>
              ))}
              <button disabled={!!busy} onClick={() => autoEdit(req)}
                className="mt-1 w-full rounded bg-violet-600 px-3 py-1.5 font-medium text-white hover:bg-violet-500 disabled:opacity-50">
                Redo the auto edit
              </button>
              <p className="text-[11px] text-neutral-500">Replaces your timeline. You can undo it.</p>
            </div>
          </details>
          <button onClick={undo} disabled={!past.length} title="Undo (Ctrl+Z)" className="rounded px-2 py-1 hover:bg-white/5 disabled:opacity-30">↶</button>
          <button onClick={redo} disabled={!future.length} title="Redo (Ctrl+Shift+Z)" className="rounded px-2 py-1 hover:bg-white/5 disabled:opacity-30">↷</button>
          <button onClick={render} disabled={!plan || !!rendering}
            className="rounded bg-white px-4 py-1.5 font-medium text-black hover:bg-neutral-200 disabled:opacity-50">
            {rendering ? `Rendering ${Math.round((job?.progress ?? 0) * 100)}%` : "Export MP4"}
          </button>
          {job?.status === "done" && job.output && (
            <a href={exportUrl(job)} download className="rounded bg-emerald-500 px-3 py-1.5 font-medium text-black">Download</a>
          )}
        </div>
      </header>

      {/* Middle row: inspector, preview, chat */}
      <div className="grid min-h-0 min-w-0 grid-cols-[260px_minmax(0,1fr)_320px]">
        <aside className="flex min-h-0 flex-col border-r border-white/10 bg-[#111319] text-sm">
          <div className="flex border-b border-white/10">
            {(["cuts", "clip"] as const).map((t) => (
              <button key={t} onClick={() => setLeftTab(t)}
                className={`flex-1 px-2 py-2 text-xs ${leftTab === t ? "border-b-2 border-violet-400 text-white" : "text-neutral-500"}`}>
                {t === "cuts" ? `Cuts${plan?.removed.length ? ` (${plan.removed.length})` : ""}` : "Clip"}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {leftTab === "cuts" && plan && (
              <>
                {plan.message && <p className="mb-3 rounded bg-violet-500/10 p-2 text-xs text-violet-200">Message: {plan.message}</p>}
                {plan.removed.length === 0 && <p className="text-xs text-neutral-500">No fillers or repeats were cut. Turn on "Cut fillers & repeats" under Auto edit.</p>}
                <ul className="space-y-1.5">
                  {plan.removed.map((r) => (
                    <li key={`${r.start}-${r.end}`} className="rounded border border-white/5 bg-white/[0.02] p-2 text-xs">
                      <div className="flex items-center justify-between text-neutral-500">
                        <span>{short(r.start)} · {KIND_LABEL[r.kind] ?? r.kind}</span>
                        <button className="text-violet-300 hover:underline" onClick={() => commit(restore(plan, r, media.duration_s))}>Put back</button>
                      </div>
                      <div className="mt-1 text-neutral-300 line-through decoration-red-400/70">{r.text}</div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {leftTab === "clip" && (
              sel && plan && selected !== null ? (
                <div className="space-y-3 text-xs">
                  <p className="text-sm font-medium text-white">Clip {selected + 1} of {plan.segments.length}</p>
                  <dl className="grid grid-cols-2 gap-y-1 text-neutral-400">
                    <dt>Source in</dt><dd className="text-right tabular-nums text-neutral-200">{timecode(sel.src_in)}</dd>
                    <dt>Source out</dt><dd className="text-right tabular-nums text-neutral-200">{timecode(sel.src_out)}</dd>
                    <dt>Length</dt><dd className="text-right tabular-nums text-neutral-200">{segDur(sel).toFixed(2)}s</dd>
                  </dl>
                  <label className="block">Punch-in zoom: {sel.zoom.toFixed(2)}×
                    <input type="range" min={1} max={MAX_ZOOM} step={0.05} value={sel.zoom} className="w-full"
                      onPointerDown={onTrimStart} onChange={(e) => live(setClip(plan, selected, { zoom: Number(e.target.value) }))} />
                  </label>
                  <label className="block">Frame left/right
                    <input type="range" min={0} max={1} step={0.01} value={sel.focus_x ?? 0.5} className="w-full"
                      onPointerDown={onTrimStart} onChange={(e) => live(setClip(plan, selected, { focus_x: Number(e.target.value) }))} />
                  </label>
                  <label className="block">Frame up/down
                    <input type="range" min={0} max={1} step={0.01} value={sel.focus_y ?? 0.4} className="w-full"
                      onPointerDown={onTrimStart} onChange={(e) => live(setClip(plan, selected, { focus_y: Number(e.target.value) }))} />
                  </label>
                  <div className="flex gap-2">
                    <button onClick={doPunch} className="flex-1 rounded border border-white/10 py-1.5 hover:bg-white/5">{sel.zoom > 1 ? "Remove punch-in" : "Punch in"}</button>
                    <button onClick={doDelete} className="flex-1 rounded border border-red-400/30 py-1.5 text-red-300 hover:bg-red-500/10">Delete clip</button>
                  </div>
                  <p className="text-neutral-500">Drag a clip&apos;s left or right edge on the timeline to trim it.</p>
                </div>
              ) : <p className="text-xs text-neutral-500">Click a clip on the timeline to adjust it.</p>
            )}
          </div>
        </aside>

        <section className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1">
            {plan && (
              <Preview ref={preview} src={proxyUrl(media.media_id)} plan={plan}
                sourceRatio={media.width / Math.max(1, media.height)} onTime={setPlayhead} onPlayingChange={setPlaying} />
            )}
            {!plan && (
              <div className="flex h-full items-center justify-center text-sm text-neutral-400">{busy ?? error ?? "Loading…"}</div>
            )}
          </div>
          <div className="flex items-center gap-3 border-t border-white/10 bg-[#111319] px-3 py-1.5 text-xs">
            <button onClick={() => preview.current?.toggle()} disabled={!plan}
              className="w-16 rounded bg-white/10 py-1 font-medium hover:bg-white/20">{playing ? "❚❚ Pause" : "▶ Play"}</button>
            <span className="tabular-nums text-neutral-300">{timecode(playhead)} / {timecode(total)}</span>
            {plan && <span className="text-neutral-500">{plan.segments.length} clips · {media.duration_s.toFixed(0)}s original</span>}
            {busy && plan && <span className="text-violet-300">{busy}</span>}
            {error && <span className="truncate text-red-300">{error}</span>}
            {warnings.slice(0, 1).map((w) => <span key={w} className="truncate text-amber-300">⚠ {w}</span>)}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col border-l border-white/10 bg-[#111319] text-sm">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
            <span className="font-medium">Editor chat</span>
            <span className="text-[11px] text-neutral-500">{mode === "claude" ? "Claude editor" : mode === "rules" ? "Free mode" : ""}</span>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {messages.map((m, i) => (
              <div key={i} className={m.from === "you" ? "text-right" : ""}>
                <span className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-left ${m.from === "you" ? "bg-violet-600 text-white" : "bg-white/5"}`}>{m.text}</span>
              </div>
            ))}
            <div ref={chatEnd} />
          </div>
          <form className="flex gap-2 border-t border-white/10 p-2" onSubmit={(e) => { e.preventDefault(); void chat(); }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} disabled={!plan || !!busy}
              placeholder='"remove the ums", "cut 0:12 to 0:18"'
              className="min-w-0 flex-1 rounded border border-white/10 bg-[#1b1e26] px-2 py-1.5 outline-none focus:border-violet-400" />
            <button type="submit" disabled={!plan || !!busy || !draft.trim()} className="rounded bg-white/10 px-3 hover:bg-white/20 disabled:opacity-40">Send</button>
          </form>
        </aside>
      </div>

      {/* Timeline */}
      <div className="flex min-h-0 min-w-0 flex-col overflow-hidden border-t border-white/10">
        <div className="flex items-center gap-2 border-b border-white/10 bg-[#111319] px-3 py-1 text-xs">
          <button onClick={doSplit} disabled={!plan} title="Split at playhead (S)" className="rounded px-2 py-1 hover:bg-white/10">✂ Split</button>
          <button onClick={doDelete} disabled={selected === null} title="Delete clip (Del)" className="rounded px-2 py-1 hover:bg-white/10 disabled:opacity-30">🗑 Delete</button>
          <button onClick={doPunch} disabled={!plan} title="Punch-in on/off (P)" className="rounded px-2 py-1 hover:bg-white/10">🔍 Punch-in</button>
          <span className="ml-3 text-neutral-500">Space play · S split · Del delete · P punch-in · Ctrl+Z undo · drag clip edges to trim</span>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-neutral-500">Zoom</span>
            <input type="range" min={4} max={400} value={pps} onChange={(e) => setPps(Number(e.target.value))} className="w-32" />
          </div>
        </div>
        <div className="min-h-0 min-w-0 flex-1">
          {plan && (
            <Timeline plan={plan} pps={pps} playhead={playhead} selected={selected} waveform={wave} words={words}
              onSeek={seek} onSelect={onSelect}
              onTrimStart={onTrimStart} onTrim={onTrim} onZoom={setPps} />
          )}
        </div>
      </div>
    </div>
  );
}
