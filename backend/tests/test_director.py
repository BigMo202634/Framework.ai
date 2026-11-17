"""Creative director: which words get cut, and how cuts land on the timeline."""

import json

import pytest

from app.brain.director import (ClaudeDirector, Cut, Direction, RuleDirector, creative_cuts,
                                describe_transcript, subtract)
from app.engine.audio import Interval
from app.engine.transcribe import Transcript, Word


def make(text: str, gap: float = 0.1, word: float = 0.3) -> Transcript:
    words, t = [], 0.5
    for i, w in enumerate(text.split()):
        words.append(Word(i=i, start=round(t, 3), end=round(t + word, 3), text=w))
        t += word + gap
    return Transcript(model="test", language="en", words=words)


def cut_text(t: Transcript, d: Direction) -> list[str]:
    return [" ".join(w.text for w in t.words[c.first:c.last + 1]) for c in d.cuts]


def kept_text(t: Transcript, d: Direction) -> str:
    gone = {i for c in d.cuts for i in range(c.first, c.last + 1)}
    return " ".join(w.text for w in t.words if w.i not in gone)


def test_fillers_are_cut():
    t = make("Hello everyone. Um, today I want to, uh, show you em the setup.")
    d = RuleDirector().direct(t)
    assert kept_text(t, d) == "Hello everyone. today I want to, show you the setup."
    assert {c.kind for c in d.cuts} == {"filler"}


def test_you_know_only_when_it_is_padding():
    t = make("We had to, you know, move the network. Do you know what happened?")
    d = RuleDirector().direct(t)
    assert cut_text(t, d) == ["you know,"]


def test_stutter_keeps_the_second_take():
    t = make("Hello. Hello, everyone. I, I knew it would fail.")
    d = RuleDirector().direct(t)
    assert kept_text(t, d) == "Hello, everyone. I knew it would fail."


def test_grammatical_repeat_is_not_a_stutter():
    t = make("Because the system has done it, it has streamed before.")
    assert RuleDirector().direct(t).cuts == []


def test_false_start_is_cut():
    t = make("So we went to the, so we went to the church to help them.")
    d = RuleDirector().direct(t)
    assert kept_text(t, d) == "so we went to the church to help them."
    assert d.cuts[0].kind in {"stutter", "retake"}


def test_abandoned_phrase_is_cut():
    t = make("I wanted to show the the I wanted to show you the camera.")
    d = RuleDirector().direct(t)
    assert kept_text(t, d) == "I wanted to show you the camera."


def test_rhythmic_repetition_is_kept():
    # Parallel phrasing is a creative choice, not a mistake.
    t = make("I tested the live, I tested the network, I tested everything.")
    assert RuleDirector().direct(t).cuts == []


def test_x_or_y_is_kept():
    t = make("It does not mean the system is okay to stream or the specification of the system is okay to stream.")
    assert RuleDirector().direct(t).cuts == []


def test_repeated_sentence_keeps_the_later_take():
    t = make("This laptop cannot handle live streaming at all. "
             "Okay. This laptop cannot handle live streaming at all. Next point.")
    d = RuleDirector().direct(t)
    assert any(c.kind == "repetition" and c.first == 0 for c in d.cuts)


def test_cut_intervals_leave_breathing_room():
    t = make("Today um we start.", gap=0.4)
    d = RuleDirector().direct(t)
    cc = creative_cuts(t, d, duration=10)
    (iv,) = cc.intervals
    today, um, we = t.words[0], t.words[1], t.words[2]
    assert today.end < iv.start < um.start
    assert um.end < iv.end < we.start
    assert cc.removed[0].text == "um" and cc.removed[0].kind == "filler"


def test_subtract_splits_and_drops_slivers():
    keep = [Interval(start=0, end=10)]
    out = subtract(keep, [Interval(start=2, end=3), Interval(start=3.1, end=4)], min_len=0.2)
    assert [(i.start, i.end) for i in out] == [(0, 2), (4, 10)]


def test_describe_transcript_has_indexes_and_times():
    text = describe_transcript(make("Hello there. Second line here."))
    assert text.splitlines()[0].startswith("[0.5s] 0:Hello 1:there.")
    assert "2:Second" in text.splitlines()[1]


class FakeResponse:
    def __init__(self, payload, stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.content = [type("B", (), {"type": "text", "text": json.dumps(payload)})()]


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        self.payload, self.stop_reason = payload, stop_reason
        self.beta = type("Beta", (), {"messages": self})()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.payload, self.stop_reason)


def test_claude_director_request_and_result():
    t = make("Um so here is the point. Funny thing, um, it worked. Bye.")
    client = FakeClient({"message": "The point, and it worked.",
                         "cuts": [{"first": 0, "last": 0, "kind": "filler", "reason": "um"},
                                  {"first": 99, "last": 120, "kind": "filler", "reason": "out of range"}]})
    d = ClaudeDirector(client=client).direct(t)
    assert d.director == "claude" and d.message == "The point, and it worked."
    assert [(c.first, c.last) for c in d.cuts] == [(0, 0)]  # out-of-range cut dropped
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "0:Um" in call["messages"][0]["content"] and "Rule findings" in call["messages"][0]["content"]


@pytest.mark.parametrize("payload,stop", [
    ({"message": "x", "cuts": [{"first": 0, "last": 11, "kind": "off_message", "reason": "all"}]}, "end_turn"),
    ({"message": "x", "cuts": []}, "refusal"),
])
def test_claude_director_falls_back_to_rules(payload, stop):
    t = make("Um so here is the point. Funny thing, um, it worked. Bye.")
    d = ClaudeDirector(client=FakeClient(payload, stop)).direct(t)
    assert d.director == "rules"
    assert cut_text(t, d) == ["Um", "um,"]
