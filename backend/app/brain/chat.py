"""Timeline chat: turns a plain-English instruction into timeline commands.

Two interpreters with the same output:
- RuleChat: free, offline, understands common phrasings. Used when no API key is set.
- ClaudeChat: Claude reads the instruction plus a summary of the timeline and returns commands
  as structured JSON. Used when ANTHROPIC_API_KEY is set.

Either way the commands go through app.engine.commands and the validator, so the chat can
never produce something the renderer can't handle.
"""

from __future__ import annotations

import json
import logging
import os
import re

from pydantic import BaseModel

from app.engine.commands import Command
from app.engine.plan import EditPlan

log = logging.getLogger("framework.chat")


class ChatResult(BaseModel):
    reply: str
    commands: list[Command]


# ----------------------------------------------------------------------------- rule-based

_TIME = r"(\d+(?::\d{1,2})?(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?"


def _t(text: str) -> float:
    if ":" in text:
        m, s = text.split(":", 1)
        return int(m) * 60 + float(s)
    return float(text)


ASPECT_WORDS = [
    (r"9\s*:\s*16|vertical|portrait|tiktok|reels?|shorts|story", "9:16"),
    (r"16\s*:\s*9|horizontal|landscape|youtube|widescreen", "16:9"),
    (r"1\s*:\s*1|square", "1:1"),
    (r"4\s*:\s*5|feed post", "4:5"),
    (r"original (size|format)|keep (the )?original", "source"),
]


class RuleChat:
    name = "rules"

    def interpret(self, message: str, plan: EditPlan) -> ChatResult:
        text = message.lower().strip()
        cmds: list[Command] = []

        rng = re.search(rf"(?:from|between|at)?\s*{_TIME}\s*(?:to|-|–|and|until)\s*{_TIME}", text)
        first = re.search(rf"first\s+{_TIME}", text)
        last = re.search(rf"last\s+{_TIME}", text)

        if re.search(r"\b(cut|remove|delete|drop|trim)\b", text) and not re.search(r"silence|pause", text):
            if first:
                cmds.append(Command(op="cut", start=0, end=_t(first.group(1))))
            elif last:
                cmds.append(Command(op="cut", start=max(0.0, plan.duration - _t(last.group(1))), end=plan.duration))
            elif rng:
                cmds.append(Command(op="cut", start=_t(rng.group(1)), end=_t(rng.group(2))))

        if re.search(r"(no|remove|without|stop|turn off)\s+(the\s+)?(punch|zoom)", text):
            if rng and re.search(r"zoom", text):
                cmds.append(Command(op="zoom", start=_t(rng.group(1)), end=_t(rng.group(2)), zoom=1.0))
            else:
                cmds.append(Command(op="punch_ins", enabled=False))
        elif re.search(r"\b(zoom|punch)", text):
            amount = re.search(r"(\d{1,3})\s*%", text)
            z = 1 + int(amount.group(1)) / 100 if amount else (1.3 if "more" in text or "close" in text else 1.2)
            if rng:
                cmds.append(Command(op="zoom", start=_t(rng.group(1)), end=_t(rng.group(2)), zoom=min(2.0, z)))
            elif re.search(r"add|put|bring back|turn on", text):
                cmds.append(Command(op="punch_ins", enabled=True))

        if not cmds or not any(c.op == "cut" for c in cmds):
            for pattern, aspect in ASPECT_WORDS:
                if re.search(pattern, text) and re.search(r"make|change|switch|convert|format|export|for|to", text):
                    cmds.append(Command(op="set_aspect", aspect=aspect))
                    break

        if re.search(r"tight|faster|fast|punchy|snappy|cut (the )?(silence|pause)s? (more|harder)|less pause", text):
            cmds.append(Command(op="replan", padding_s=0.06, keep_pauses_under_s=0.1, remove_silences=True))
        elif re.search(r"slow|breath|natural|longer pause|more pause|too (tight|fast|choppy)|relax", text):
            cmds.append(Command(op="replan", padding_s=0.25, keep_pauses_under_s=0.6, remove_silences=True))
        elif re.search(r"(keep|don.t (cut|remove)) (the )?(silence|pause)s?|no silence (removal|cutting)", text):
            cmds.append(Command(op="replan", remove_silences=False))

        filler = r"(um+s?|uh+s?|ems?|erm|fillers?|stutter\w*|repeat\w*|retakes?|false starts?)"
        if re.search(rf"(keep|leave|put back|bring back|restore|don.t (cut|remove)) (the |all )?(\w+ )?{filler}", text):
            cmds.append(Command(op="replan", creative_cuts=False))
        elif re.search(rf"(cut|remove|clean|delete|take out|get rid of)\b.*{filler}", text):
            cmds.append(Command(op="replan", creative_cuts=True))

        if re.search(r"caption|subtitle|subs\b|text on screen", text):
            style = next((st for st in ("karaoke", "pop", "clean", "boxed") if st in text), None)
            if style is None and re.search(r"\bbox", text):
                style = "boxed"
            off = re.search(r"(remove|no|turn off|hide|delete|without|take off)\b.*(caption|subtitle|subs)", text)
            cmds.append(Command(op="captions", enabled=not off, caption_style=style))

        if cmds:
            return ChatResult(reply="On it.", commands=cmds)
        return ChatResult(reply=(
            "I didn't catch that. In free mode I understand things like: \"cut 0:12 to 0:18\", "
            "\"remove the first 3 seconds\", \"zoom in from 10s to 15s\", \"no punch-ins\", "
            "\"make it 16:9\", \"make it tighter\", \"keep more natural pauses\", \"remove the ums\" or \"add captions\". "
            "Add an Anthropic API key to talk to the Claude editor in your own words."
        ), commands=[])


# ----------------------------------------------------------------------------- Claude

SYSTEM = """You are the editor inside FRAMEWORK AI, a video editing app for people who don't edit.
The user describes a change to their talking-head video. Translate it into timeline commands.

Commands (all times are seconds on the EDITED timeline the user sees, not the original recording):
- set_aspect: aspect one of "9:16", "16:9", "1:1", "4:5", "source"
- cut: remove start..end
- zoom: set zoom (1.0 = none, up to 2.0) on start..end. Remove a zoom with zoom 1.0
- punch_ins: enabled true/false, alternating punch-ins on every other cut across the whole video
- replan: re-cut the pacing from the original audio. padding_s is breathing room kept around speech
  (0.05 tight to 0.3 relaxed), keep_pauses_under_s keeps pauses shorter than this (0.1 tight to 0.8
  natural), remove_silences false keeps everything. creative_cuts true cuts fillers (um, uh), stutters,
  retakes and repeated lines found in the transcript; false puts them back. Replan resets earlier
  manual cuts, so mention that.
- captions: enabled true/false; caption_style one of "pop" (word pops in highlight colour),
  "karaoke" (word lights up), "clean" (plain white lines), "boxed" (text on a dark box), or null to keep.

Rules: only use the commands above. Leave unused fields null. If the request needs something not
available yet (music, sound effects, colour, b-roll, transitions), return no commands and say plainly it's
coming in a later version. Keep the reply to one or two short, friendly sentences."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "commands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["set_aspect", "cut", "zoom", "punch_ins", "replan", "captions"]},
                    "aspect": {"type": ["string", "null"], "enum": ["9:16", "16:9", "1:1", "4:5", "source", None]},
                    "start": {"type": ["number", "null"]},
                    "end": {"type": ["number", "null"]},
                    "zoom": {"type": ["number", "null"]},
                    "enabled": {"type": ["boolean", "null"]},
                    "padding_s": {"type": ["number", "null"]},
                    "keep_pauses_under_s": {"type": ["number", "null"]},
                    "remove_silences": {"type": ["boolean", "null"]},
                    "creative_cuts": {"type": ["boolean", "null"]},
                    "caption_style": {"type": ["string", "null"], "enum": ["pop", "karaoke", "clean", "boxed", None]},
                },
                "required": ["op", "aspect", "start", "end", "zoom", "enabled", "padding_s",
                             "keep_pauses_under_s", "remove_silences", "creative_cuts", "caption_style"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reply", "commands"],
    "additionalProperties": False,
}


def describe_timeline(plan: EditPlan) -> str:
    lines, t = [], 0.0
    for i, s in enumerate(plan.segments, 1):
        lines.append(f"{i}. {t:.2f}-{t + s.duration:.2f}s (zoom {s.zoom})")
        t += s.duration
        if i >= 200:
            lines.append(f"... {len(plan.segments) - 200} more parts")
            break
    caps = f"Captions: {plan.captions.style}." if plan.captions.enabled else "Captions: off."
    return (f"{caps} Format: {plan.output.aspect}. Edited length: {plan.duration:.2f}s in "
            f"{len(plan.segments)} parts.\n" + "\n".join(lines))


class ClaudeChat:
    name = "claude"
    model = "claude-opus-5-5"

    def __init__(self, api_key: str | None = None):
        import anthropic  # imported lazily so the free mode works without the package

        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def interpret(self, message: str, plan: EditPlan) -> ChatResult:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            # Simple translation job: low effort keeps it fast and cheap (about a cent per message).
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
            # If a safety classifier declines, retry on the default fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": f"Timeline:\n{describe_timeline(plan)}\n\nRequest: {message}"}],
        )
        if response.stop_reason == "refusal":
            return ChatResult(reply="Claude declined that request. Try wording it differently.", commands=[])
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return ChatResult(**json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("Unparseable chat reply: %s", text[:300])
            raise RuntimeError("The AI editor returned something I couldn't read. Please try again.") from exc


def get_chat(prefer: str | None = None, api_key: str | None = None):
    """Claude when an API key is configured (and not explicitly turned off), else the free rules."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if prefer != "rules" and key:
        try:
            return ClaudeChat(key)
        except ImportError:
            log.warning("anthropic package not installed; using rule-based chat")
    return RuleChat()
