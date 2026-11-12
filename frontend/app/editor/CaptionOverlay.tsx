"use client";

// Draws the caption line for the current moment on top of the preview, styled to match what
// the export burns in (same font, same size relative to the frame, same highlight rules).

import { useEffect, useRef, useState } from "react";
import { fontUrl, type CapLine, type CaptionSettings } from "@/lib/api";

type Props = { lines: CapLine[]; settings: CaptionSettings; time: number; frameW: number; frameH: number };

export default function CaptionOverlay({ lines, settings, time, frameW, frameH }: Props) {
  const box = useRef<HTMLDivElement | null>(null);
  const [h, setH] = useState(0);
  useEffect(() => {
    const el = box.current?.parentElement;
    if (!el) return;
    const ro = new ResizeObserver(() => setH(el.clientHeight));
    ro.observe(el);
    setH(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  const line = lines.find((l) => time >= l.start && time < l.end);
  // Same formula as the backend: min(6% of height, 10% of width) of the output frame.
  const scale = h / Math.max(1, frameH);
  const fontPx = Math.min(frameH * 0.06, frameW * 0.1) * settings.size * scale;
  const active = line ? line.words.findIndex((w) => time >= w.start && time < w.end) : -1;
  const boxed = settings.style === "boxed";
  const outline = settings.style === "clean" ? 0.03 : 0.06;
  const stroke = Math.max(1, fontPx * outline);

  return (
    <div ref={box} className="pointer-events-none absolute inset-x-0" style={{ top: `${settings.position * 100}%`, transform: "translateY(-50%)" }}>
      <style>{`@font-face{font-family:"FW Inter Black";src:url("${fontUrl("Inter-Black.otf")}");font-display:swap}
@font-face{font-family:"FW Inter ExtraBold";src:url("${fontUrl("Inter-ExtraBold.otf")}");font-display:swap}
@keyframes fw-pop{from{transform:scale(1.18)}to{transform:scale(1)}}`}</style>
      {line && (
        <p className="mx-auto text-center leading-[1.15]" style={{
          width: "84%",
          fontFamily: settings.style === "clean" ? '"FW Inter ExtraBold", sans-serif' : '"FW Inter Black", sans-serif',
          fontSize: fontPx,
          color: settings.color,
          textTransform: settings.uppercase ? "uppercase" : "none",
          textShadow: boxed ? "none" : `0 0 ${stroke}px #000, 0 0 ${stroke}px #000, ${stroke / 2}px ${stroke / 2}px ${stroke}px rgba(0,0,0,.6)`,
          WebkitTextStroke: boxed ? undefined : `${stroke * 0.6}px #000`,
          paintOrder: "stroke fill",
        }}>
          <span style={boxed ? { background: "rgba(0,0,0,.75)", padding: `${fontPx * 0.08}px ${fontPx * 0.18}px`, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" } : undefined}>
            {line.words.map((w, i) => {
              const lit = settings.style !== "clean" && i === active;
              return (
                <span key={`${line.start}-${i}-${lit}`} style={{
                  color: lit ? settings.highlight : undefined,
                  display: "inline-block",
                  animation: lit && settings.style === "pop" ? "fw-pop 90ms ease-out" : undefined,
                  marginRight: i < line.words.length - 1 ? "0.28em" : 0,
                }}>{w.text}</span>
              );
            })}
          </span>
        </p>
      )}
    </div>
  );
}
