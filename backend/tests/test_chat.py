from app.brain.chat import RuleChat, _SCHEMA, describe_timeline
from app.engine.commands import Command, CommandError, apply, split_at
from app.engine.plan import EditPlan, Segment
from app.engine.validate import validate_plan
from tests.test_engine import fake_info

import pytest


def plan3() -> EditPlan:
    # three 4 s parts from a 20 s source -> 12 s edit
    return EditPlan(media_id="m", segments=[
        Segment(src_in=0, src_out=4), Segment(src_in=6, src_out=10, zoom=1.15), Segment(src_in=12, src_out=16)])


def test_split_maps_output_time_to_source():
    p = plan3()
    idx = split_at(p, 5.0)  # 1 s into the second part -> source 7.0
    assert idx == 2
    assert p.segments[1].src_out == 7.0 and p.segments[2].src_in == 7.0
    assert p.duration == 12


def test_split_snaps_instead_of_making_slivers():
    p = plan3()
    assert split_at(p, 4.05) == 1
    assert len(p.segments) == 3


def test_cut_across_segments():
    p, msg = apply(plan3(), Command(op="cut", start=2, end=6))
    assert p.duration == pytest.approx(8)
    assert [(s.src_in, s.src_out) for s in p.segments] == [(0, 2), (8, 10), (12, 16)]
    assert "Cut" in msg
    assert validate_plan(p, fake_info(duration=20), "m").ok


def test_cut_everything_is_refused():
    with pytest.raises(CommandError):
        apply(plan3(), Command(op="cut", start=0, end=12))


def test_zoom_range_and_punch_toggle():
    p, _ = apply(plan3(), Command(op="zoom", start=1, end=3, zoom=1.3))
    assert [s.zoom for s in p.segments][:3] == [1.0, 1.3, 1.0]
    p, _ = apply(p, Command(op="punch_ins", enabled=False))
    assert all(s.zoom == 1.0 for s in p.segments)


def test_aspect_change_resets_size():
    p, _ = apply(plan3(), Command(op="set_aspect", aspect="16:9"))
    assert p.output.aspect == "16:9" and p.output.width is None


@pytest.mark.parametrize("msg,op,check", [
    ("cut 0:02 to 0:05", "cut", lambda c: (c.start, c.end) == (2, 5)),
    ("remove the first 3 seconds", "cut", lambda c: (c.start, c.end) == (0, 3)),
    ("delete the last 2s", "cut", lambda c: (c.start, c.end) == (10, 12)),
    ("zoom in from 4 to 8", "zoom", lambda c: c.zoom == 1.2),
    ("zoom in 40% from 1 to 2", "zoom", lambda c: abs(c.zoom - 1.4) < 1e-9),
    ("no punch-ins please", "punch_ins", lambda c: c.enabled is False),
    ("make it 16:9 for youtube", "set_aspect", lambda c: c.aspect == "16:9"),
    ("make it tighter and punchy", "replan", lambda c: c.keep_pauses_under_s == 0.1),
    ("too choppy, keep more natural pauses", "replan", lambda c: c.keep_pauses_under_s == 0.6),
])
def test_rule_chat_understands(msg, op, check):
    result = RuleChat().interpret(msg, plan3())
    assert result.commands, msg
    assert result.commands[0].op == op
    assert check(result.commands[0])


def test_rule_chat_says_when_it_doesnt_understand():
    result = RuleChat().interpret("add fireworks", plan3())
    assert result.commands == []
    assert "didn't catch" in result.reply


def test_claude_schema_matches_command_fields():
    item = _SCHEMA["properties"]["commands"]["items"]["properties"]
    assert set(item) == set(Command.model_fields)
    assert "12.00s" in describe_timeline(plan3())


def test_claude_chat_request_and_parsing_without_network():
    """Runs the real SDK against a fake HTTP server: checks what we send and that we parse the reply."""
    import json

    import anthropic
    import httpx2 as httpx  # the Anthropic SDK 2.x uses httpx2

    from app.brain.chat import ClaudeChat

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta", "")
        reply = {"reply": "Done.", "commands": [{"op": "cut", "aspect": None, "start": 0, "end": 2, "zoom": None,
                 "enabled": None, "padding_s": None, "keep_pauses_under_s": None, "remove_silences": None}]}
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(reply)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    chat = ClaudeChat.__new__(ClaudeChat)
    chat.client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = chat.interpret("cut the first two seconds", plan3())

    assert result.commands[0].op == "cut" and result.commands[0].end == 2
    assert seen["body"]["model"] == "claude-opus-5-5"
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"
    assert seen["body"]["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["beta"]
    assert "Request: cut the first two seconds" in seen["body"]["messages"][0]["content"]
