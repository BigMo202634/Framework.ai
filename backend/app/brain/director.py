"""Creative director: reads the transcript and decides which words to cut.

The job, in the user's words: get the message the creator is trying to pass, and cut what is not
necessary, unless it is a reaction or a word that creates suspense, a joke or momentum.

Two directors with the same output (a list of word ranges to remove):
- RuleDirector (free): fillers (um, uh, em...), stutters ("I, I knew"), false starts and
  retakes ("so we went, so we went to..."), and a sentence said twice. It never judges content.
- ClaudeDirector: gets the transcript plus the rule findings as hints, works out the message,
  and also trims rambling or off-message parts, while protecting jokes, suspense, reactions and
  momentum. Used when ANTHROPIC_API_KEY is set.

Cuts are word ranges, so they can be shown to the user as struck-through text and turned into
source-time intervals for the timeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.engine.audio import Interval
from app.engine.plan import RemovedPart
from app.engine.transcribe import Transcript, Word

log = logging.getLogger("framework.director")

CutKind = Literal["filler", "stutter", "retake", "repetition", "off_message"]


class Cut(BaseModel):
    first: int  # word index, inclusive
    last: int  # word index, inclusive
    kind: CutKind
    reason: str = ""


class Direction(BaseModel):
    director: str
    message: str = ""  # one-line summary of what the creator is trying to say
    cuts: list[Cut] = Field(default_factory=list)


class CreativeCuts(BaseModel):
    """What the planner needs from the director: time ranges to drop and a readable list of them."""
    director: str
    message: str = ""
    intervals: list[Interval] = Field(default_factory=list)
    removed: list[RemovedPart] = Field(default_factory=list)


# ----------------------------------------------------------------------------- helpers

def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9']", "", text.lower())


def ends_sentence(w: Word) -> bool:
    return w.text.endswith((".", "?", "!"))


# Always safe to cut. "Hmm" and "ah" can be reactions, so they are only cut mid-sentence.
FILLERS = {"um", "umm", "uh", "uhh", "em", "emm", "erm", "er", "mm", "mmm", "uhm", "ehm"}
SOFT_FILLERS = {"hmm", "ah", "eh"}
# Parenthetical phrases: cut when set off by commas or a pause, i.e. not part of the sentence.
FILLER_PHRASES = [("you", "know"), ("i", "mean"), ("you", "see")]
# Words people restart on ("I, I think"). A repeated word with a comma that isn't one of these is
# usually grammar ("the system has done it, it has streamed"), not a stutter.
STUTTER_STARTERS = {"i", "we", "you", "they", "he", "she", "the", "a", "an", "and", "but", "so", "to", "my",
                    "our", "this", "that", "it's", "i'm", "we're", "there", "if", "because", "when", "what"}


def _merge(cuts: list[Cut]) -> list[Cut]:
    """Sort, drop overlaps (keeping the first cut's kind), and join adjacent cuts."""
    out: list[Cut] = []
    for c in sorted(cuts, key=lambda c: (c.first, -c.last)):
        if out and c.first <= out[-1].last + 1:
            if c.last > out[-1].last:
                out[-1] = out[-1].model_copy(update={"last": c.last})
            continue
        out.append(c)
    return out


# ----------------------------------------------------------------------------- rule-based

class RuleDirector:
    name = "rules"

    def __init__(self, max_retake_words: int = 14, sentence_similarity: float = 0.75):
        self.max_retake_words = max_retake_words
        self.sentence_similarity = sentence_similarity

    def direct(self, transcript: Transcript) -> Direction:
        words = transcript.words
        cuts = (self.fillers(words) + self.stutters(words) + self.retakes(words)
                + self.repeated_sentences(words))
        return Direction(director=self.name, cuts=_merge(cuts))

    @staticmethod
    def fillers(words: list[Word]) -> list[Cut]:
        cuts = []
        for i, w in enumerate(words):
            n = norm(w.text)
            if n in FILLERS:
                cuts.append(Cut(first=i, last=i, kind="filler", reason=f'"{w.text}"'))
            elif n in SOFT_FILLERS and 0 < i < len(words) - 1 and not ends_sentence(words[i - 1]):
                cuts.append(Cut(first=i, last=i, kind="filler", reason=f'"{w.text}"'))
        for a, b in FILLER_PHRASES:
            for i in range(len(words) - 1):
                if norm(words[i].text) != a or norm(words[i + 1].text) != b:
                    continue
                before = words[i - 1] if i > 0 else None
                after = words[i + 2] if i + 2 < len(words) else None
                set_off_before = before is None or before.text.endswith((",", ".", "?", "!")) \
                    or words[i].start - before.end > 0.25
                set_off_after = words[i + 1].text.endswith((",", ".")) or after is None \
                    or after.start - words[i + 1].end > 0.25
                if set_off_before and set_off_after:
                    cuts.append(Cut(first=i, last=i + 1, kind="filler", reason=f'"{a} {b}"'))
        return cuts

    @staticmethod
    def stutters(words: list[Word]) -> list[Cut]:
        """A word or short phrase said twice in a row: keep the second one."""
        cuts = []
        i = 0
        while i < len(words):
            for n in (3, 2, 1):
                a = [norm(w.text) for w in words[i:i + n]]
                b = [norm(w.text) for w in words[i + n:i + 2 * n]]
                if len(b) == n and a == b and all(a) and not (n == 1 and a[0] in {"no", "very", "so", "really", "bye"}) \
                        and not (n == 1 and words[i].text.endswith(",") and a[0] not in STUTTER_STARTERS):
                    cuts.append(Cut(first=i, last=i + n - 1, kind="stutter",
                                    reason=f'said twice: "{" ".join(w.text for w in words[i:i + n])}"'))
                    i += n - 1
                    break
            i += 1
        return cuts

    def retakes(self, words: list[Word]) -> list[Cut]:
        """A false start: the speaker starts a phrase, stops, and starts it again.

        Found as the same 3+ opening words appearing again a few words later. Everything from
        the first attempt up to the restart is cut, so the cleaner later take stays.
        """
        cuts = []
        normed = [norm(w.text) for w in words]
        i = 0
        while i < len(words):
            found = False
            for gap in range(1, self.max_retake_words + 1):
                j = i + gap
                n = 0
                while j + n < len(words) and i + n < j and normed[i + n] and normed[i + n] == normed[j + n]:
                    n += 1
                if n >= 3 or (n >= 2 and gap <= 4):
                    if n == gap and gap <= 3:  # short stutter, handled by stutters()
                        continue
                    # A finished sentence, or a lot of new words before the restart, means the first
                    # attempt carried content ("X or Y", an aside): not a false start.
                    if any(ends_sentence(w) for w in words[i:j - 1]) or gap - n > 3:
                        continue
                    # Parallel phrasing for rhythm ("I tested the live, I tested the network, I tested
                    # everything") repeats the opening a third time. That's style: keep it.
                    if self._repeats_again(normed, i, j, gap):
                        continue
                    cuts.append(Cut(first=i, last=j - 1, kind="retake",
                                    reason=f'restarted: "{" ".join(w.text for w in words[i:j])}"'))
                    i = j
                    found = True
                    break
            if not found:
                i += 1
        return cuts

    @staticmethod
    def _repeats_again(normed: list[str], i: int, j: int, gap: int) -> bool:
        before = normed[max(0, i - gap - 5):i]
        after = normed[j + 1:j + gap + 6]
        return normed[i] in before or normed[i] in after

    def repeated_sentences(self, words: list[Word]) -> list[Cut]:
        """The same sentence said twice (a second take of a whole line): keep the later one."""
        sentences: list[tuple[int, int]] = []
        start = 0
        for i, w in enumerate(words):
            if ends_sentence(w) or i == len(words) - 1:
                sentences.append((start, i))
                start = i + 1
        cuts = []
        for k, (a0, a1) in enumerate(sentences):
            sa = [norm(w.text) for w in words[a0:a1 + 1] if norm(w.text) and norm(w.text) not in FILLERS]
            if len(sa) < 4:
                continue
            for b0, b1 in sentences[k + 1:k + 4]:
                if words[b0].start - words[a1].end > 30:
                    break
                sb = [norm(w.text) for w in words[b0:b1 + 1] if norm(w.text) and norm(w.text) not in FILLERS]
                if not sb:
                    continue
                overlap = len(set(sa) & set(sb)) / len(set(sa) | set(sb))
                if overlap >= self.sentence_similarity:
                    cuts.append(Cut(first=a0, last=a1, kind="repetition",
                                    reason="said again a moment later"))
                    break
        return cuts


# ----------------------------------------------------------------------------- Claude

SYSTEM = """You are the creative director of a short-form video editor for creators (talking-head videos).
You get the transcript of one raw take, word by word, as `index:word` with a timestamp before each line.

Your job:
1. Understand the message the creator is trying to pass. Write it in one sentence.
2. Decide which words to cut so the video delivers that message tightly:
   - filler: um, uh, em, "you know", "I mean" used as padding.
   - stutter: a word or phrase said twice in a row.
   - retake: a false start the speaker abandoned and said again; keep the better (usually later) take.
   - repetition: a point already made that adds nothing the second time.
   - off_message: rambling, tangents or setup that does not serve the message.
3. Never cut a joke, a punchline, suspense, a reaction (laughs, "wow", "wait"), a hook, or a line
   that builds momentum or emotion, even if it looks like a filler or a repeat. Repetition used for
   emphasis or rhythm is a creative choice: keep it.
4. After your cuts, the remaining words must read as natural, grammatical speech. Never cut part
   of a word sequence in a way that leaves a broken sentence. Keep the first greeting/hook and the sign-off.
5. Be decisive but not destructive: most good takes lose 10-30% of words. Do not go above 45%.

You also get "rule findings": cuts a simple detector suggests. Use them as hints; drop any that
would hurt the edit, and add what they miss.

Return cuts as inclusive word index ranges. Keep each reason under 12 words."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "cuts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first": {"type": "integer"},
                    "last": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["filler", "stutter", "retake", "repetition", "off_message"]},
                    "reason": {"type": "string"},
                },
                "required": ["first", "last", "kind", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "cuts"],
    "additionalProperties": False,
}


def describe_transcript(transcript: Transcript, words_per_line: int = 14) -> str:
    """Compact transcript: one line per sentence (or every N words) with its start time."""
    lines, line = [], []
    for w in transcript.words:
        if not line:
            line.append(f"[{w.start:.1f}s]")
        line.append(f"{w.i}:{w.text}")
        if ends_sentence(w) or len(line) > words_per_line:
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    return "\n".join(lines)


class ClaudeDirector:
    name = "claude"
    model = "claude-opus-5-5"

    def __init__(self, api_key: str | None = None, client=None):
        if client is None:
            import anthropic  # lazy, so the free mode works without the package

            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.rules = RuleDirector()

    def direct(self, transcript: Transcript) -> Direction:
        if not transcript.words:
            return Direction(director=self.name)
        hints = self.rules.direct(transcript).cuts
        hint_text = "\n".join(f"{c.first}-{c.last} {c.kind}: {c.reason}" for c in hints) or "(none)"
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM,
            # Editorial judgement over a few thousand words: medium effort is enough and keeps
            # a 5-minute video to a few cents.
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content":
                       f"Transcript:\n{describe_transcript(transcript)}\n\nRule findings:\n{hint_text}"}],
        )
        if response.stop_reason == "refusal":
            log.warning("Director declined; falling back to rules")
            return Direction(director="rules", cuts=hints)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The AI director returned something I couldn't read. Please try again.") from exc
        n = len(transcript.words)
        cuts = []
        for c in data.get("cuts", []):
            try:
                cut = Cut(**c)
            except ValueError:
                continue
            if 0 <= cut.first <= cut.last < n:
                cuts.append(cut)
        cuts = _merge(cuts)
        removed = sum(c.last - c.first + 1 for c in cuts)
        if removed > 0.6 * n:  # guard against a runaway answer
            log.warning("Director tried to cut %d of %d words; using rules instead", removed, n)
            return Direction(director="rules", message=data.get("message", ""), cuts=hints)
        return Direction(director=self.name, message=data.get("message", ""), cuts=cuts)


def get_director(prefer: str | None = None, api_key: str | None = None):
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if prefer != "rules" and key:
        try:
            return ClaudeDirector(key)
        except ImportError:
            log.warning("anthropic package not installed; using rule-based director")
    return RuleDirector()


# ----------------------------------------------------------------------------- to timeline

def creative_cuts(transcript: Transcript, direction: Direction, duration: float,
                  breath_s: float = 0.06) -> CreativeCuts:
    """Turn word cuts into source-time intervals to remove.

    A cut runs from just after the last kept word before it to just before the next kept word,
    leaving `breath_s` on each side, so the pause around a filler goes too and the join sounds
    like one sentence. Silence removal handles the rest of the pacing.
    """
    words = transcript.words
    intervals: list[Interval] = []
    parts: list[RemovedPart] = []
    for c in direction.cuts:
        prev_end = words[c.first - 1].end if c.first > 0 else 0.0
        next_start = words[c.last + 1].start if c.last + 1 < len(words) else duration
        gap_before = max(0.0, words[c.first].start - prev_end)
        gap_after = max(0.0, next_start - words[c.last].end)
        start = prev_end + min(breath_s, gap_before / 2) if c.first > 0 else 0.0
        end = next_start - min(breath_s, gap_after / 2) if c.last + 1 < len(words) else duration
        if end - start <= 0.03:
            continue
        intervals.append(Interval(start=round(start, 3), end=round(min(end, duration), 3)))
        parts.append(RemovedPart(start=round(words[c.first].start, 3), end=round(words[c.last].end, 3),
                                 kind=c.kind, reason=c.reason,
                                 text=" ".join(w.text for w in words[c.first:c.last + 1])))
    return CreativeCuts(director=direction.director, message=direction.message, intervals=intervals, removed=parts)


def subtract(keep: list[Interval], remove: list[Interval], min_len: float) -> list[Interval]:
    """Keep ranges minus remove ranges; pieces shorter than min_len are dropped."""
    out: list[Interval] = []
    remove = sorted(remove, key=lambda r: r.start)
    for k in keep:
        pieces = [k]
        for r in remove:
            nxt = []
            for p in pieces:
                if r.end <= p.start or r.start >= p.end:
                    nxt.append(p)
                    continue
                if r.start > p.start:
                    nxt.append(Interval(start=p.start, end=r.start))
                if r.end < p.end:
                    nxt.append(Interval(start=r.end, end=p.end))
            pieces = nxt
        out.extend(p for p in pieces if p.duration >= min_len)
    return out
