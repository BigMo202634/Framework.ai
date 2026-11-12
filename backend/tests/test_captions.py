"""Captions: words land on the edited timeline, lines group sensibly, ASS output renders."""

import subprocess

import pytest

from app.engine.captions import FONTS_DIR, CapWord, build_ass, caption_lines, group_lines, map_words
from app.engine.plan import CaptionSettings, EditPlan, Segment
from app.engine.transcribe import Transcript, Word
from tests.conftest import needs_ffmpeg


def tr(*words):
    return Transcript(model="t", language="en", words=[Word(i=i, start=a, end=b, text=t) for i, (t, a, b) in enumerate(words)])


def test_words_follow_the_edit_and_cut_words_disappear():
    t = tr(("Hello,", 0.5, 0.9), ("um,", 1.0, 1.3), ("everyone.", 1.5, 2.0), ("Welcome", 5.0, 5.5))
    plan = EditPlan(media_id="x", segments=[Segment(src_in=0.4, src_out=0.95), Segment(src_in=1.45, src_out=2.1),
                                             Segment(src_in=4.9, src_out=6.0)])
    words = map_words(t, plan)
    assert [w.text for w in words] == ["Hello,", "everyone.", "Welcome"]
    # 'everyone.' starts 0.05 s into clip 2, which starts at 0.55 s on the edited timeline.
    assert words[1].start == pytest.approx(0.6)
    assert words[2].start == pytest.approx(0.55 + 0.65 + 0.1)


def test_early_whisper_start_still_counts():
    # Whisper put the word's start before the clip; most of it is inside, so keep it.
    t = tr(("Hello,", 4.2, 5.2))
    plan = EditPlan(media_id="x", segments=[Segment(src_in=4.8, src_out=6.0)])
    assert [w.text for w in map_words(t, plan)] == ["Hello,"]


def test_lines_break_on_count_pause_and_sentence_end():
    ws = [CapWord(text=x, start=s, end=s + 0.2) for x, s in
          [("one", 0), ("two", 0.3), ("three", 0.6), ("four", 0.9), ("end.", 1.2), ("new", 1.5), ("late", 3.0)]]
    lines = group_lines(ws, per_line=3)
    assert [[w.text for w in l.words] for l in lines] == [["one", "two", "three"], ["four", "end."], ["new"], ["late"]]
    # The highlight on each word lasts until the next word starts.
    assert lines[0].words[0].end == pytest.approx(0.3)
    # Lines never overlap.
    assert all(a.end <= b.start + 1e-9 for a, b in zip(lines, lines[1:]))


def test_ass_highlights_one_word_per_event():
    lines = group_lines([CapWord(text="hi", start=0, end=0.3), CapWord(text="there", start=0.3, end=0.6)], 3)
    ass = build_ass(lines, CaptionSettings(enabled=True, style="karaoke", highlight="#FF0000"), 1080, 1920)
    events = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(events) == 2
    assert "{\\c&H000000FF}HI{" in events[0] and "{\\c&H000000FF}THERE{" in events[1]
    assert "PlayResY: 1920" in ass and "Inter Black" in ass
    clean = build_ass(lines, CaptionSettings(enabled=True, style="clean", uppercase=False), 1920, 1080)
    assert [l for l in clean.splitlines() if l.startswith("Dialogue:")][0].endswith("hi there")


def test_ass_escapes_override_braces():
    lines = group_lines([CapWord(text="{bad}\\N", start=0, end=0.3)], 3)
    ass = build_ass(lines, CaptionSettings(enabled=True, style="clean", uppercase=False), 640, 360)
    assert "(bad)N" in ass


def test_font_is_bundled():
    assert (FONTS_DIR / "Inter-Black.otf").is_file() and (FONTS_DIR / "OFL.txt").is_file()


@needs_ffmpeg
def test_burned_captions_change_the_picture(tmp_path):
    """Render a plain clip with and without captions: the captioned frame must differ where the text is."""
    import numpy as np

    from app.engine.render import render
    from app.media.probe import probe
    from tests.conftest import make_talk_video

    src = make_talk_video(tmp_path / "talk.mp4", seconds=3, width=640, height=360)
    info = probe(src)
    plan = EditPlan(media_id="x", segments=[Segment(src_in=0.0, src_out=2.0)])
    plan.output.aspect = "16:9"
    words = tr(("HELLO", 0.2, 0.8), ("WORLD", 0.8, 1.6))
    plan.captions = CaptionSettings(enabled=True, style="boxed", position=0.5)
    ass = build_ass(caption_lines(words, plan), plan.captions, 1920, 1080)
    plain = render(plan, info, src, tmp_path / "plain.mp4")
    capped = render(plan, info, src, tmp_path / "capped.mp4", captions_ass=ass)

    def frame(p):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(p), "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "gray", "-s", "192x108", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).reshape(108, 192).astype(int)

    diff = np.abs(frame(plain) - frame(capped))
    assert diff[44:64, 60:132].mean() > 20  # caption box in the middle
    assert diff[:20].mean() < 3  # top of the frame untouched
