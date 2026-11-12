"""Animated captions: transcript words -> short lines on the edited timeline -> an ASS file.

ASS (Advanced SubStation Alpha) is the subtitle format libass renders inside FFmpeg. It supports
per-word colour and animation, which is how the "word lights up as it's spoken" look is made:
each word of a line gets its own event, showing the whole line with that word highlighted.

The font (Inter, SIL OFL) ships with the app, so captions look the same on every computer.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from app.engine.plan import CaptionSettings, EditPlan
from app.engine.transcribe import Transcript

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
LINE_HOLD_S = 0.25  # how long a line stays after its last word, unless the next line starts
MAX_GAP_S = 0.6  # a pause longer than this starts a new line


class CapWord(BaseModel):
    text: str
    start: float  # edited-timeline seconds
    end: float


class CapLine(BaseModel):
    start: float
    end: float
    words: list[CapWord]


def map_words(transcript: Transcript, plan: EditPlan) -> list[CapWord]:
    """Place each kept word on the edited timeline. Words that were cut don't appear.

    A word belongs to the clip it overlaps most, if that overlap is at least 0.15 s or half the
    word. (Whisper often starts the first word of a phrase a little early, before the clip.)
    """
    offsets, t = [], 0.0
    for seg in plan.segments:
        offsets.append(t)
        t += seg.duration
    out: list[CapWord] = []
    for w in transcript.words:
        best, best_ov = None, 0.0
        for k, seg in enumerate(plan.segments):
            ov = min(w.end, seg.src_out) - max(w.start, seg.src_in)
            if ov > best_ov:
                best, best_ov = k, ov
        if best is None or best_ov < min(0.15, 0.5 * max(0.01, w.end - w.start)):
            continue
        seg = plan.segments[best]
        start = offsets[best] + max(w.start, seg.src_in) - seg.src_in
        end = offsets[best] + min(w.end, seg.src_out) - seg.src_in
        out.append(CapWord(text=w.text, start=round(start, 3), end=round(max(end, start + 0.06), 3)))
    out.sort(key=lambda w: w.start)
    return out


def group_lines(words: list[CapWord], per_line: int) -> list[CapLine]:
    lines: list[list[CapWord]] = []
    for w in words:
        cur = lines[-1] if lines else None
        if (cur is None or len(cur) >= per_line or w.start - cur[-1].end > MAX_GAP_S
                or cur[-1].text.endswith((".", "?", "!"))):
            lines.append([w])
        else:
            cur.append(w)
    out: list[CapLine] = []
    for i, ws in enumerate(lines):
        nxt = lines[i + 1][0].start if i + 1 < len(lines) else None
        end = ws[-1].end + LINE_HOLD_S
        if nxt is not None:
            end = min(end, nxt)
        # Each word stays lit until the next word starts, so the highlight never blinks off mid-line.
        stretched = [w.model_copy(update={"end": ws[j + 1].start if j + 1 < len(ws) else end})
                     for j, w in enumerate(ws)]
        out.append(CapLine(start=ws[0].start, end=round(max(end, ws[0].start + 0.1), 3), words=stretched))
    return out


def caption_lines(transcript: Transcript, plan: EditPlan) -> list[CapLine]:
    return group_lines(map_words(transcript, plan), plan.captions.words_per_line)


# ----------------------------------------------------------------------------- ASS

def _ass_color(hex_color: str, alpha: int = 0) -> str:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    rgb = m.group(1) if m else "FFFFFF"
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str, upper: bool) -> str:
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return text.upper() if upper else text


def build_ass(lines: list[CapLine], cap: CaptionSettings, width: int, height: int) -> str:
    font_size = round(min(height * 0.06, width * 0.1) * cap.size)
    outline = max(2, round(font_size * (0.06 if cap.style != "clean" else 0.03)))
    shadow = max(1, round(font_size * 0.03))
    font = "Inter ExtraBold" if cap.style == "clean" else "Inter Black"
    base, hi = _ass_color(cap.color), _ass_color(cap.highlight)
    black = _ass_color("#000000")
    if cap.style == "boxed":
        border_style, outline_c, back_c, outline = 3, _ass_color("#000000", 0x40), _ass_color("#000000", 0x40), round(font_size * 0.18)
    else:
        border_style, outline_c, back_c = 1, black, _ass_color("#000000", 0x80)
    margin = round(width * 0.08)
    x, y = width // 2, round(height * cap.position)

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{font_size},{base},{hi},{outline_c},{back_c},0,0,0,0,100,100,0,0,{border_style},{outline},{shadow},5,{margin},{margin},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    pos = f"\\pos({x},{y})"
    for line in lines:
        texts = [_clean(w.text, cap.uppercase) for w in line.words]
        if cap.style == "clean":
            events.append(f"Dialogue: 0,{_ts(line.start)},{_ts(line.end)},Cap,,0,0,0,,{{{pos}\\fad(80,60)}}{' '.join(texts)}")
            continue
        for i, w in enumerate(line.words):
            parts = []
            for j, t in enumerate(texts):
                if j == i:
                    pop = "\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)" if cap.style == "pop" else ""
                    parts.append(f"{{\\c{hi}{pop}}}{t}{{\\c{base}\\fscx100\\fscy100}}")
                else:
                    parts.append(t)
            fade = "\\fad(60,0)" if i == 0 else ""
            events.append(f"Dialogue: 0,{_ts(w.start)},{_ts(w.end)},Cap,,0,0,0,,{{{pos}{fade}}}{' '.join(parts)}")
    return head + "\n".join(events) + "\n"
